"""tasks · AI-powered task operations (breakdown, planning)."""

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, chat, imperal_id_of, is_no_connection_error
from models_return import AiBreakdownResult
from imperal_sdk.chat.error_codes import PERMISSION_DENIED, INTERNAL
from error_codes import TASKS_BRIDGE_ERROR, TASKS_TASK_NOT_FOUND

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
