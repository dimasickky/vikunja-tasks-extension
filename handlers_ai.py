"""tasks · AI-powered task operations (breakdown, planning)."""

import json
import logging
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import (
    api_get,
    api_post,
    bridge_error_result,
    chat,
    fetch_all_pages,
    imperal_id_of,
    is_no_connection_error,
    resolve_project_id,
)
from models_return import (
    AiBreakdownResult,
    AiEstimateDurationResult,
    AiPlanMyDayResult,
    AiProjectSummaryResult,
    PlannedTaskItem,
)
from imperal_sdk.chat.error_codes import INTERNAL, PERMISSION_DENIED, VALIDATION_MISSING_FIELD
from error_codes import TASKS_BRIDGE_ERROR, TASKS_PROJECT_NOT_FOUND, TASKS_TASK_NOT_FOUND

log = logging.getLogger("tasks")


def _require_user(ctx) -> str | ActionResult:
    iid = imperal_id_of(ctx)
    if not iid:
        return ActionResult.error("No authenticated user on context.", code=PERMISSION_DENIED)
    return iid


def _bridge_error_msg(resp: dict, default_prefix: str) -> str:
    if is_no_connection_error(resp):
        return "No Vikunja connected. Connect your Vikunja in the tasks panel first."
    detail = resp.get("detail")
    if isinstance(detail, dict):
        detail = detail.get("detail") or detail.get("error") or detail.get("message") or str(detail)
    return f"{default_prefix}: {detail}"


def _parse_subtask_titles(text: str, max_count: int) -> list[str]:
    """Extract clean subtask titles from LLM numbered/bulleted list."""
    titles = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^[\d]+[.)]\s*|^[-*•]\s*", "", line).strip()
        if cleaned and len(cleaned) >= 3:
            titles.append(cleaned[:250])
        if len(titles) >= max_count:
            break
    return titles


# ─── Params ───────────────────────────────────────────────────────────────── #

class AiBreakdownParams(BaseModel):
    task_id: int = Field(..., description="ID of the task to break down into subtasks.")
    count: int = Field(5, ge=2, le=10, description="Number of subtasks to generate (2–10).")
    context: Optional[str] = Field(None, description="Optional extra context or instructions for the breakdown.")


# ─── Handler ──────────────────────────────────────────────────────────────── #

@chat.function(
    "ai_breakdown_task",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["create:task"],
    event="task.created",
    description=(
        "Break a task into subtasks using AI. "
        "Fetches the task title and description, generates N actionable subtask titles, "
        "then creates each as a real Vikunja subtask. "
        "Use when user says 'break this task into subtasks', 'разбей задачу', "
        "'create a plan', or similar. "
        "Returns the list of created subtask IDs and titles."
    ),
    data_model=AiBreakdownResult,
)
async def ai_breakdown_task(ctx, params: AiBreakdownParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    try:
        # 1. Fetch parent task details.
        task = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
        if isinstance(task, dict) and task.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(task, "Couldn't fetch task"), code=TASKS_BRIDGE_ERROR)

        title = task.get("title", "")
        description = (task.get("description") or "").strip()
        project_id = task.get("project_id")

        if not title:
            return ActionResult.error("Task not found or has no title.", code=TASKS_TASK_NOT_FOUND)

        # 2. Ask AI to generate subtask titles.
        context_block = f"\nAdditional context: {params.context}" if params.context else ""
        desc_block = f"\nDescription: {description[:800]}" if description else ""
        prompt = (
            f"You are a project planning assistant. "
            f"Break the following task into exactly {params.count} clear, actionable subtasks.\n\n"
            f"Task: {title}{desc_block}{context_block}\n\n"
            f"Return ONLY a numbered list of subtask titles, one per line:\n"
            f"1. First subtask\n"
            f"2. Second subtask\n"
            f"...\n\n"
            f"Each title: concise (max 80 chars), starts with an action verb, "
            f"specific enough to assign to one person."
        )

        completion = await ctx.ai.complete(prompt)
        raw_text = completion.text if isinstance(completion.text, str) else "\n".join(
            b.text for b in completion.text if hasattr(b, "text")
        )

        titles = _parse_subtask_titles(raw_text, params.count)
        if not titles:
            return ActionResult.error(
                "AI didn't return a valid subtask list. Try rephrasing the task description.",
                retryable=True,
                code=INTERNAL,
            )

        # 3. Create subtasks via bridge.
        created = []
        failed = []
        for t in titles:
            resp = await api_post(ctx, f"/v1/tasks/{params.task_id}/subtasks", {
                "imperal_id": imperal_id,
                "title":       t,
                "description": "",
            })
            if resp.get("status") == "error":
                failed.append(t)
                log.warning("ai_breakdown_task: subtask create failed for %r: %s", t, resp)
            else:
                created.append({"task_id": resp["id"], "title": resp["title"]})

        if not created:
            return ActionResult.error(
                f"AI generated {len(titles)} subtask titles but all creates failed. "
                "Check your Vikunja connection.",
                retryable=True,
                code=TASKS_BRIDGE_ERROR,
            )

        failed_note = f" ({len(failed)} failed)" if failed else ""
        return ActionResult.success(
            summary=(
                f"Created {len(created)} subtasks for '{title}'{failed_note}: "
                + ", ".join(s["title"] for s in created[:3])
                + ("..." if len(created) > 3 else "")
            ),
            data={
                "task_id":         params.task_id,
                "task_title":      title,
                "project_id":      project_id,
                "subtasks_created": created,
                "count":           len(created),
                "refresh_panels":  ["sidebar", "editor"],
            },
        )

    except Exception as e:
        log.error("ai_breakdown_task: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


def _extract_json(text: str):
    """Extract JSON object or array from LLM completion text."""
    if not text:
        return None
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.DOTALL)
    if match:
        candidate = match.group(1)
    else:
        match2 = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        candidate = match2.group(1) if match2 else cleaned
    try:
        return json.loads(candidate)
    except Exception:
        return None


# ─── ai_estimate_duration ─────────────────────────────────────────────────── #

class AiEstimateDurationParams(BaseModel):
    task_id: int = Field(..., description="ID of the task to estimate duration for.")
    context: Optional[str] = Field(None, description="Optional extra context regarding complexity or scope.")


@chat.function(
    "ai_estimate_duration",
    action_type="read",
    chain_callable=True,
    id_projection="task_id",
    description=(
        "Estimate duration (in minutes) for a task using AI. Analyzes task title, "
        "description, priority, and subtasks. Returns estimated minutes, confidence, "
        "rationale, and suggested breakdown."
    ),
    data_model=AiEstimateDurationResult,
)
async def ai_estimate_duration(ctx, params: AiEstimateDurationParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    try:
        task = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
        if isinstance(task, dict) and task.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(task, "Couldn't fetch task"), code=TASKS_BRIDGE_ERROR)

        title = task.get("title", "")
        description = (task.get("description") or "").strip()
        priority = task.get("priority", 0)

        if not title:
            return ActionResult.error("Task not found or has no title.", code=TASKS_TASK_NOT_FOUND)

        prompt = (
            f"You are a technical estimation assistant. Estimate the completion time in minutes "
            f"for the following task.\n\n"
            f"Task: {title}\n"
            f"Priority: {priority}\n"
            f"Description: {description[:1000] if description else 'None'}\n"
            + (f"Additional context: {params.context}\n" if params.context else "")
            + "\nRespond with ONLY a JSON object with keys:\n"
            "- \"estimated_minutes\": integer (e.g. 45, 120)\n"
            "- \"confidence\": string (\"low\", \"medium\", or \"high\")\n"
            "- \"rationale\": string explaining the estimate in 1-2 sentences\n"
            "- \"suggested_breakdown\": list of strings showing major phases\n"
        )

        completion = await ctx.ai.complete(prompt)
        raw_text = completion.text if isinstance(completion.text, str) else "\n".join(
            b.text for b in completion.text if hasattr(b, "text")
        )

        parsed = _extract_json(raw_text) or {}
        est_min = parsed.get("estimated_minutes")
        if not isinstance(est_min, int) or est_min <= 0:
            est_min = 60
        conf = parsed.get("confidence") if parsed.get("confidence") in ("low", "medium", "high") else "medium"
        rationale = parsed.get("rationale") or f"Estimated {est_min}m based on task scope."
        breakdown = parsed.get("suggested_breakdown") if isinstance(parsed.get("suggested_breakdown"), list) else []

        hours_str = f"{est_min // 60}h {est_min % 60}m" if est_min >= 60 else f"{est_min}m"
        return ActionResult.success(
            summary=f"Estimated duration for '{title}': ~{hours_str} ({conf} confidence). {rationale}",
            data={
                "task_id": params.task_id,
                "task_title": title,
                "estimated_minutes": est_min,
                "confidence": conf,
                "rationale": rationale,
                "suggested_breakdown": [str(x) for x in breakdown],
                "refresh_panels": [],
            },
        )
    except Exception as e:
        log.error("ai_estimate_duration: %s", e)
        return ActionResult.error("An unexpected error occurred during duration estimation.", retryable=True, code=INTERNAL)


# ─── ai_plan_my_day ───────────────────────────────────────────────────────── #

class AiPlanMyDayParams(BaseModel):
    date: Optional[str] = Field(None, description="Target planning date in YYYY-MM-DD. Defaults to today.")
    available_hours: Optional[float] = Field(8.0, ge=1.0, le=24.0, description="Available working hours for the day.")
    project_id: Optional[int] = Field(None, description="Optional project ID to limit planning.")
    project_name: Optional[str] = Field(None, description="Optional project name to look up.")
    context: Optional[str] = Field(None, description="Optional focus area or custom goal for the day.")


@chat.function(
    "ai_plan_my_day",
    action_type="read",
    chain_callable=True,
    id_projection="",
    description=(
        "Generate an optimized, realistic daily work schedule using AI. "
        "Selects and prioritizes open, overdue, and upcoming tasks to fit available hours."
    ),
    data_model=AiPlanMyDayResult,
)
async def ai_plan_my_day(ctx, params: AiPlanMyDayParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    try:
        project_id = params.project_id
        if not project_id and params.project_name:
            project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
            if not project_id:
                return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)

        base_params: dict = {"imperal_id": imperal_id}
        if project_id:
            base_params["filter"] = f"project_id = {project_id}"
        raw_tasks = await fetch_all_pages(ctx, base_params)
        open_tasks = [t for t in raw_tasks if not t.get("done")][:30]

        if not open_tasks:
            return ActionResult.success(
                summary="You have no open tasks to schedule. Enjoy your free time!",
                data={
                    "plan_date": params.date or "today",
                    "summary": "No pending tasks found.",
                    "scheduled_tasks": [],
                    "total_estimated_minutes": 0,
                    "recommendations": ["All caught up! Consider backlog grooming or new project ideation."],
                    "refresh_panels": ["sidebar", "editor"],
                },
            )

        tasks_summary = []
        for t in open_tasks:
            tasks_summary.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "priority": t.get("priority", 0),
                "due_date": t.get("due_date"),
                "percent_done": t.get("percent_done", 0),
            })

        max_minutes = int((params.available_hours or 8.0) * 60)
        prompt = (
            f"You are an executive productivity assistant. Create a realistic daily work plan.\n"
            f"Available time: {params.available_hours or 8.0} hours ({max_minutes} minutes).\n"
            f"Target date: {params.date or 'today'}\n"
            + (f"User focus: {params.context}\n" if params.context else "")
            + f"Open candidate tasks:\n{json.dumps(tasks_summary, indent=2)}\n\n"
            "Select the most impactful tasks that fit comfortably within the available time.\n"
            "Respond ONLY with a JSON object with keys:\n"
            "- \"summary\": concise overview of the day's focus\n"
            "- \"scheduled_tasks\": list of objects with keys:\n"
            "    \"task_id\" (int), \"title\" (str), \"priority\" (int), \"time_slot\" (str e.g. \"09:00 - 10:30\"),\n"
            "    \"estimated_minutes\" (int), \"reason\" (str)\n"
            "- \"total_estimated_minutes\": integer total sum of scheduled minutes\n"
            "- \"recommendations\": list of 2-3 short productivity tips for the day\n"
        )

        completion = await ctx.ai.complete(prompt)
        raw_text = completion.text if isinstance(completion.text, str) else "\n".join(
            b.text for b in completion.text if hasattr(b, "text")
        )

        parsed = _extract_json(raw_text) or {}
        summary = parsed.get("summary") or "Daily schedule prepared."
        sched = parsed.get("scheduled_tasks") or []
        total_est = parsed.get("total_estimated_minutes") or sum(item.get("estimated_minutes", 30) for item in sched)
        recs = parsed.get("recommendations") or ["Take regular breaks", "Focus on top priority first"]

        scheduled_items = []
        for s in sched:
            scheduled_items.append({
                "task_id": s.get("task_id", 0),
                "title": s.get("title", ""),
                "priority": s.get("priority", 0),
                "due_date": s.get("due_date"),
                "time_slot": s.get("time_slot"),
                "estimated_minutes": s.get("estimated_minutes", 30),
                "reason": s.get("reason"),
            })

        return ActionResult.success(
            summary=f"Plan ready for {params.date or 'today'}: {len(scheduled_items)} tasks scheduled (~{total_est} min). {summary}",
            data={
                "plan_date": params.date or "today",
                "summary": summary,
                "scheduled_tasks": scheduled_items,
                "total_estimated_minutes": total_est,
                "recommendations": [str(r) for r in recs],
                "refresh_panels": ["sidebar", "editor"],
            },
        )
    except Exception as e:
        log.error("ai_plan_my_day: %s", e)
        return ActionResult.error("An unexpected error occurred while planning your day.", retryable=True, code=INTERNAL)


# ─── ai_project_summary ──────────────────────────────────────────────────── #

class AiProjectSummaryParams(BaseModel):
    project_id: Optional[int] = Field(None, description="Integer project ID.")
    project_name: Optional[str] = Field(None, description="Project name to look up.")


@chat.function(
    "ai_project_summary",
    action_type="read",
    chain_callable=True,
    id_projection="project_id",
    description=(
        "Generate an intelligent executive summary of a project or board using AI. "
        "Analyzes total tasks, completed vs overdue tasks, bottlenecks, health status, "
        "and suggests immediate strategic priorities."
    ),
    data_model=AiProjectSummaryResult,
)
async def ai_project_summary(ctx, params: AiProjectSummaryParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    try:
        project_id = params.project_id
        if not project_id and params.project_name:
            project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
            if not project_id:
                return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)

        if not project_id:
            return ActionResult.error("Either project_id or project_name is required.", code=VALIDATION_MISSING_FIELD)

        proj_resp = await api_get(ctx, f"/v1/projects/{project_id}", {"imperal_id": imperal_id})
        if isinstance(proj_resp, dict) and proj_resp.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(proj_resp, "Couldn't fetch project"), code=TASKS_BRIDGE_ERROR)
        project_title = proj_resp.get("title", f"Project {project_id}")

        tasks = await fetch_all_pages(ctx, {"imperal_id": imperal_id, "filter": f"project_id = {project_id}"})
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("done"))
        in_progress = sum(1 for t in tasks if not t.get("done") and (t.get("percent_done", 0) > 0 or t.get("priority", 0) >= 3))
        overdue = sum(1 for t in tasks if not t.get("done") and t.get("due_date") and t.get("due_date") < "2026-11-25T00:00:00Z")

        prompt = (
            f"You are a project management executive assistant. Analyze this project status:\n"
            f"Project: {project_title} (ID: {project_id})\n"
            f"Total tasks: {total}\n"
            f"Completed: {completed}\n"
            f"In Progress: {in_progress}\n"
            f"Overdue: {overdue}\n\n"
            f"Task sample:\n{json.dumps([{'id': t.get('id'), 'title': t.get('title'), 'done': t.get('done'), 'priority': t.get('priority')} for t in tasks[:20]], indent=2)}\n\n"
            "Provide an executive assessment in JSON format with keys:\n"
            "- \"health\": string (\"on_track\", \"at_risk\", or \"behind\")\n"
            "- \"key_findings\": list of 2-4 bullet observations\n"
            "- \"next_priorities\": list of 2-3 immediate actionable next steps\n"
            "- \"summary_markdown\": markdown formatted executive briefing (2-3 paragraphs)\n"
        )

        completion = await ctx.ai.complete(prompt)
        raw_text = completion.text if isinstance(completion.text, str) else "\n".join(
            b.text for b in completion.text if hasattr(b, "text")
        )

        parsed = _extract_json(raw_text) or {}
        health = parsed.get("health") if parsed.get("health") in ("on_track", "at_risk", "behind") else ("on_track" if overdue == 0 else "at_risk")
        findings = parsed.get("key_findings") or [f"{completed}/{total} tasks completed."]
        priorities = parsed.get("next_priorities") or ["Focus on in-progress tasks."]
        md = parsed.get("summary_markdown") or f"### Status of {project_title}\n\nTotal tasks: {total}, Completed: {completed}."

        return ActionResult.success(
            summary=f"Project '{project_title}' health: {health.upper()}. {completed}/{total} completed, {overdue} overdue.",
            data={
                "project_id": project_id,
                "project_title": project_title,
                "total_tasks": total,
                "completed_tasks": completed,
                "in_progress_tasks": in_progress,
                "overdue_tasks": overdue,
                "health": health,
                "key_findings": [str(x) for x in findings],
                "next_priorities": [str(x) for x in priorities],
                "summary_markdown": md,
                "refresh_panels": [],
            },
        )
    except Exception as e:
        log.error("ai_project_summary: %s", e)
        return ActionResult.error("An unexpected error occurred while generating project summary.", retryable=True, code=INTERNAL)
