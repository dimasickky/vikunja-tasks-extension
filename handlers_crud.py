"""tasks · CRUD lifecycle functions (create / update / complete / delete)."""

from typing import Optional, List
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from imperal_sdk import sdl
from imperal_sdk.chat import ActionResult

import asyncio
import logging

from app import api_get, api_post, api_delete, chat, imperal_id_of, is_no_connection_error, resolve_project_id
from panels_task import _toggle_checklist_item
from models_return import (
    CreateTaskResult,
    UpdateTaskResult,
    TaskStatusResult,
    BulkDeleteResult,
    BulkTaskResult,
    DeleteTaskResult,
    CreateSubtaskResult,
    ListSubtasksResult,
    ToggleChecklistResult,
    TaskEntity,
    SubtaskItem,
    TaskAssignee,
    TaskLabelItem,
    vikunja_priority,
    vikunja_date,
)
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, PERMISSION_DENIED
from error_codes import TASKS_BRIDGE_ERROR, TASKS_PROJECT_NOT_FOUND, TASKS_CHECKLIST_ITEM_NOT_FOUND


log = logging.getLogger("tasks")

# How many Vikunja requests a bulk operation may have in flight at once.
#
# The users of this extension mostly run small self-hosted Vikunja instances, so
# an unbounded asyncio.gather over a 200-task delete would be a self-inflicted
# thundering herd: refused connections or rate-limiting, and on a DESTRUCTIVE
# operation a partial result is genuinely expensive. Eight is enough to turn a
# 40-task cleanup from ~80 serial round trips into ~10 rounds (comfortably
# inside the 180s a normal tool call gets) while staying polite to the backend.
_BULK_CONCURRENCY = 8


class CreateTaskParams(BaseModel):
    project_id: Optional[int] = Field(None, description="Project (board) ID. Pass project_name instead if unknown.")
    project_name: Optional[str] = Field(
        None,
        description="Project name to look up (e.g. 'webhostmost tasks'). Used when project_id unknown.",
    )
    title: str = Field(..., min_length=1, max_length=250, description="Task title.")
    description: str = Field("", description="Optional description, markdown.")
    due_date: Optional[str] = Field(None, description="ISO 8601 due date (e.g. 2026-04-25T12:00:00Z).")
    priority: Optional[int] = Field(None, ge=0, le=5, description="0=none, 1=low, 2=medium, 3=high, 4=urgent, 5=critical.")
    bucket_id: Optional[int] = Field(None, description="Integer bucket ID. Use bucket_name instead if unknown.")
    bucket_name: Optional[str] = Field(None, description="Bucket/column name (e.g. 'To-Do', 'Social Media'). Auto-resolved to bucket_id. Use this instead of bucket_id when you know the name.")
    assignee: Optional[str] = Field(
        None,
        description=(
            "Name or email of person to assign (e.g. 'dmitrii@webhostmost.com'). "
            "Auto-resolved to Vikunja user. Optional — task is created even if resolution fails."
        ),
    )

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return int(v)
            except (ValueError, TypeError):
                return v
        return v


class UpdateTaskParams(BaseModel):
    task_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=5)
    percent_done: Optional[float] = Field(None, ge=0.0, le=1.0)

    @field_validator("priority", mode="before")
    @classmethod
    def coerce_priority(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            try:
                return int(v)
            except (ValueError, TypeError):
                return v
        return v
    bucket_id: Optional[int] = None
    project_id: Optional[int] = Field(None, description="Move to another project.")
    hex_color: Optional[str] = None


class CompleteTaskParams(BaseModel):
    task_id: int


class UncompleteTaskParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")


class DeleteTaskParams(BaseModel):
    task_id: int


class CreateSubtaskParams(BaseModel):
    parent_task_id: int = Field(..., description="ID of the parent task.")
    title: str = Field(..., min_length=1, max_length=250, description="Subtask title.")
    description: str = Field("", description="Optional description.")


class ListSubtasksParams(BaseModel):
    task_id: int = Field(..., description="Parent task ID to list subtasks for.")


class ToggleChecklistItemParams(BaseModel):
    task_id: int = Field(..., description="Task whose description checklist to update.")
    item_index: int = Field(..., ge=0, description="Zero-based index of the checklist item.")
    checked: bool = Field(..., description="True to mark done, False to uncheck.")


# ─── Impl functions ───────────────────────────────────────────────────────── #

def _require_user(ctx) -> str | ActionResult:
    imperal_id = imperal_id_of(ctx)
    if not imperal_id:
        return ActionResult.error("No authenticated user on context.", code=PERMISSION_DENIED)
    return imperal_id


def _bridge_error_msg(resp: dict, default_prefix: str) -> str:
    if is_no_connection_error(resp):
        return "No Vikunja connected. Connect your Vikunja in the tasks panel first."
    detail = resp.get("detail") or resp.get("error") or resp.get("message")
    if isinstance(detail, dict):
        detail = detail.get("detail") or detail.get("error") or detail.get("message")
    if not detail:
        return default_prefix
    return f"{default_prefix}: {detail}"


# ─── shared bulk machinery ──────────────────────────────────────────────── #
#
# `delete_tasks` grew all of this inline first. Pulling it out is what makes
# the next batch tool cheap to write and, more importantly, keeps every batch
# behaving the same way — the concern `extensions/batching.md` §7 raises about
# bulk handlers each ending up "на свой вкус".
#
# The ceiling is the one piece that is new here rather than extracted. It is
# not bureaucracy: these are mostly small self-hosted Vikunja instances, and a
# 500-item batch is far likelier to be a mistaken selection than a real intent.
# Refusing up front costs the caller one corrected call; discovering it half
# way through a destructive run costs them data.
MAX_BULK_ITEMS = 100


def _check_batch_size(items: list, noun: str) -> Optional[ActionResult]:
    """Reject an empty or oversized batch before any network call happens."""
    if not items:
        return ActionResult.error(f"No {noun} given.", code=VALIDATION_MISSING_FIELD)
    if len(items) > MAX_BULK_ITEMS:
        return ActionResult.error(
            f"That's {len(items)} {noun} in one call — the limit is {MAX_BULK_ITEMS}. "
            "Split it into smaller batches.",
            code=VALIDATION_MISSING_FIELD,
        )
    return None


async def _resolve_task_refs(
    ctx,
    imperal_id: str,
    sem: "asyncio.Semaphore",
    task_ids: Optional[List[int]],
    task_titles: Optional[List[str]],
    project_id: Optional[int],
) -> List[tuple[int, str]]:
    """Turn ids and/or titles into [(task_id, label)], -1 marking 'not found'.

    Title lookups fan out concurrently under the caller's semaphore: one search
    round trip each, serialised, is half the cost of a large batch. asyncio.gather
    preserves input order, so resolved titles come first and explicit ids after,
    exactly as the previous inline version ordered them.
    """
    resolved: List[tuple[int, str]] = []

    async def _resolve_title(title: str) -> tuple[int, str]:
        q: dict = {"imperal_id": imperal_id, "s": title, "per_page": 10, "page": 1}
        if project_id:
            q["filter"] = f"project_id = {project_id}"
        async with sem:
            resp = await api_get(ctx, "/v1/tasks/all", q)
        tasks = resp if isinstance(resp, list) else []
        title_lower = title.strip().lower()
        match = next(
            (t for t in tasks if t.get("title", "").strip().lower() == title_lower),
            next((t for t in tasks if title_lower in t.get("title", "").strip().lower()), None),
        )
        if match:
            return match["id"], match.get("title", title)
        return -1, title

    if task_titles:
        resolved.extend(await asyncio.gather(*[_resolve_title(t) for t in task_titles]))

    if task_ids:
        for tid in task_ids:
            resolved.append((tid, f"#{tid}"))

    return resolved


async def _run_task_batch(
    ctx,
    refs: List[tuple[int, str]],
    sem: "asyncio.Semaphore",
    verb: str,
    apply_one,
) -> List[dict]:
    """Apply `apply_one(task_id) -> resp dict` across refs, bounded, with progress.

    Returns one row per input in input order: {task_id, title, ok, error?}.
    A single failure never sinks the batch — on a bulk operation "18 of 20 went,
    these two didn't and here's why" is strictly more useful than a blanket
    failure, and for destructive work it is the difference between a recoverable
    state and a mystery.
    """
    total = len(refs)
    done = 0

    async def _one(tid: int, title: str) -> dict:
        nonlocal done
        if tid == -1:
            outcome = {"task_id": -1, "title": title, "ok": False, "error": "Task not found"}
        else:
            async with sem:
                resp = await apply_one(tid)
            if isinstance(resp, dict) and resp.get("status") == "error":
                outcome = {"task_id": tid, "title": title, "ok": False,
                           "error": _bridge_error_msg(resp, f"{verb.capitalize()} failed")}
            else:
                label = title
                if isinstance(resp, dict) and resp.get("title"):
                    label = resp["title"]
                outcome = {"task_id": tid, "title": label, "ok": True}

        # Progress is advisory: ctx.progress raises TaskCancelled if the user
        # cancelled, and by then the write has already landed on Vikunja's side.
        # Letting that surface would report a completed action as a failure.
        done += 1
        if total > 1:
            try:
                await ctx.progress(min(0.95, done / total), f"{verb.capitalize()} {done} of {total}…")
            except Exception:
                pass
        return outcome

    return list(await asyncio.gather(*[_one(tid, title) for tid, title in refs]))


async def _create_task_impl(ctx, params: CreateTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.", code=VALIDATION_MISSING_FIELD)

    # Resolve bucket_name → bucket_id if caller passed a name instead of ID.
    if params.bucket_name and not params.bucket_id:
        _KANBAN_VIEW_KINDS = {"kanban", 4}
        views_resp = await api_get(ctx, f"/v1/projects/{params.project_id}/views", {"imperal_id": imperal_id})
        views = views_resp if isinstance(views_resp, list) else []
        kanban_view = next((v for v in views if v.get("view_kind") in _KANBAN_VIEW_KINDS), None)
        if kanban_view:
            buckets_resp = await api_get(
                ctx,
                f"/v1/projects/{params.project_id}/views/{kanban_view['id']}/buckets",
                {"imperal_id": imperal_id},
            )
            buckets = buckets_resp if isinstance(buckets_resp, list) else []
            name_lower = params.bucket_name.strip().lower()
            matched = (
                next((b for b in buckets if (b.get("title") or "").strip().lower() == name_lower), None)
                or next((b for b in buckets if (b.get("title") or "").strip().lower().startswith(name_lower)), None)
                or next((b for b in buckets if name_lower in (b.get("title") or "").strip().lower()), None)
            )
            if matched:
                params.bucket_id = matched["id"]
            else:
                log.warning("create_task: bucket '%s' not found in project %s", params.bucket_name, params.project_id)

    payload = {
        "imperal_id":  imperal_id,
        "project_id":  params.project_id,
        "title":       params.title,
        "description": params.description,
    }
    if params.due_date is not None:    payload["due_date"] = params.due_date
    if params.priority is not None:    payload["priority"] = params.priority
    if params.bucket_id is not None:   payload["bucket_id"] = params.bucket_id

    resp = await api_post(ctx, "/v1/tasks", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create task"), code=TASKS_BRIDGE_ERROR)

    task_id = resp["id"]
    assigned_name: Optional[str] = None

    if params.assignee:
        assign_resp = await api_post(
            ctx,
            f"/v1/tasks/{task_id}/assign",
            {"imperal_id": imperal_id, "assignee_query": params.assignee},
        )
        if assign_resp.get("status") == "error":
            log.error("create_task: assignee '%s' resolution failed: %s", params.assignee, assign_resp.get("detail"))
        else:
            assigned_name = assign_resp.get("_resolved_username", params.assignee)

    result_data: dict = {
        "task_id":    task_id,
        "title":      resp["title"],
        "project_id": resp["project_id"],
        "due_date":   resp.get("due_date"),
        "priority":   resp.get("priority", 0),
        "bucket_id":  resp.get("bucket_id", 0),
        "refresh_panels": ["sidebar", "editor"],
    }
    if assigned_name is not None:
        result_data["assignee"] = assigned_name

    summary = f"Task created: {resp['title']} (project #{resp['project_id']})"
    if assigned_name:
        summary += f", assigned to {assigned_name}"
    summary += "."

    return ActionResult.success(summary=summary, data=result_data)


async def _update_task_impl(ctx, params: UpdateTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {"imperal_id": imperal_id}
    for field in (
        "title", "description", "due_date", "start_date", "end_date",
        "priority", "percent_done", "bucket_id", "project_id", "hex_color",
    ):
        v = getattr(params, field)
        if v is not None:
            payload[field] = v

    if len(payload) == 1:
        return ActionResult.error("No fields to update — pass at least one field.", code=VALIDATION_MISSING_FIELD)

    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update task"), code=TASKS_BRIDGE_ERROR)

    return ActionResult.success(
        summary=f"Task updated: {resp.get('title', params.task_id)}.",
        data={
            "task_id":      resp.get("id", params.task_id),
            "title":        resp.get("title"),
            "done":         resp.get("done", False),
            "due_date":     resp.get("due_date"),
            "priority":     resp.get("priority", 0),
            "percent_done": resp.get("percent_done", 0.0),
            "refresh_panels": ["sidebar", "editor"],
        },
    )


async def _complete_task_impl(ctx, params: CompleteTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        ctx, f"/v1/tasks/{params.task_id}",
        {"imperal_id": imperal_id, "done": True, "percent_done": 1.0},
    )
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't complete task"), code=TASKS_BRIDGE_ERROR)

    return ActionResult.success(
        summary=f"Task completed: {resp.get('title', params.task_id)}.",
        data={"task_id": resp.get("id", params.task_id), "done": resp.get("done", True),
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _uncomplete_task_impl(ctx, params: UncompleteTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        ctx, f"/v1/tasks/{params.task_id}",
        {"imperal_id": imperal_id, "done": False, "percent_done": 0.0},
    )
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't reopen task"), code=TASKS_BRIDGE_ERROR)

    return ActionResult.success(
        summary=f"Task reopened: {resp.get('title', params.task_id)}.",
        data={"task_id": resp.get("id", params.task_id), "done": resp.get("done", False),
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _delete_task_impl(ctx, params: DeleteTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(ctx, f"/v1/tasks/{params.task_id}", params={"imperal_id": imperal_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete task"), code=TASKS_BRIDGE_ERROR)

    return ActionResult.success(
        summary=f"Task #{params.task_id} deleted.",
        data={"task_id": params.task_id, "deleted": True, "refresh_panels": ["sidebar", "editor"]},
    )


# ─── @chat.function wrappers ──────────────────────────────────────────────── #

@chat.function(
    "create_task",
    action_type="write",
    chain_callable=True,
    id_projection="project_id",
    effects=["create:task"],
    event="task.created",
    description=(
        "Create a new task in a project. Pass project_name (e.g. 'webhostmost tasks') or project_id. "
        "The assignee field handles assignment internally — do NOT add a separate assign_task step. "
        "priority must be an integer: 0=none 1=low 2=medium 3=high 4=urgent 5=critical. "
        "due_date must be full ISO 8601 with time (e.g. '2026-06-15T00:00:00Z'), never a bare date."
    ),
    data_model=CreateTaskResult,
)
async def create_task(ctx, params: CreateTaskParams) -> ActionResult:
    return await _create_task_impl(ctx, params)


@chat.function(
    "update_task",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.updated",
    description="Update any fields of a task (title, description, due_date, priority, percent_done, bucket, etc.).",
    data_model=UpdateTaskResult,
)
async def update_task(ctx, params: UpdateTaskParams) -> ActionResult:
    return await _update_task_impl(ctx, params)


@chat.function(
    "complete_task",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.completed",
    description="Mark a task as done (done=true, percent_done=1.0).",
    data_model=TaskStatusResult,
)
async def complete_task(ctx, params: CompleteTaskParams) -> ActionResult:
    return await _complete_task_impl(ctx, params)


@chat.function(
    "uncomplete_task",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.uncompleted",
    description="Reopen a task — mark it as not done (done=false, percent_done=0). Inverse of complete_task.",
    data_model=TaskStatusResult,
)
async def uncomplete_task(ctx, params: UncompleteTaskParams) -> ActionResult:
    return await _uncomplete_task_impl(ctx, params)


@chat.function(
    "delete_task",
    action_type="destructive",
    chain_callable=True,
    id_projection="task_id",
    effects=["delete:task"],
    event="task.deleted",
    description="Permanently delete a task. Cannot be undone.",
    data_model=DeleteTaskResult,
)
async def delete_task(ctx, params: DeleteTaskParams) -> ActionResult:
    return await _delete_task_impl(ctx, params)


class DeleteTasksParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_ids: Optional[List[int]] = sdl.field(
        role="ref.target_id",
        description="List of integer task IDs to delete. Use this if you already have the IDs.",
        validation_alias=AliasChoices("task_ids", "message_ids", "ids"),
    )
    task_titles: Optional[List[str]] = Field(
        None,
        description="List of task titles to find and delete (e.g. ['Buy milk', 'Fix login bug']). Auto-resolved to task IDs.",
    )
    project_id: Optional[int] = Field(
        None,
        description="Narrow title search to a specific project. Recommended when using task_titles.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Project name to narrow title search (e.g. 'WebHostMost Tasks').",
    )


@chat.function(
    "delete_tasks",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:task"],
    event="tasks.deleted",
    description=(
        "Delete multiple tasks at once. Pass task_ids (list of integers) OR task_titles (list of names). "
        "When using task_titles, optionally pass project_name to narrow the search. "
        "Use when user asks to delete 2+ tasks in one request."
    ),
    data_model=BulkDeleteResult,
)
async def delete_tasks(ctx, params: DeleteTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if not params.task_ids and not params.task_titles:
        return ActionResult.error("Pass task_ids or task_titles.", code=VALIDATION_MISSING_FIELD)

    oversized = _check_batch_size((params.task_ids or []) + (params.task_titles or []), "tasks")
    if oversized:
        return oversized

    # Resolve project_name → project_id if needed
    if params.project_name and not params.project_id:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)

    # Both phases below fan out CONCURRENTLY, bounded by a semaphore — see
    # _resolve_task_refs / _run_task_batch, which this and the other batch
    # tools share. Sequential loops here meant ~80 serialised round trips for a
    # 40-task cleanup, walking into the 180s a normal tool call gets, and a
    # timeout half way through a DESTRUCTIVE batch is the worst outcome there
    # is: some tasks are already gone while the caller is told it all failed.
    #
    # Bounded, not unbounded: 200 concurrent DELETEs would hammer what is
    # usually a small self-hosted Vikunja. A cap of 8 fits inline comfortably —
    # which is also why this deliberately does NOT go through
    # ctx.background_task: there is no long-running work left to hand off.
    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    refs = await _resolve_task_refs(
        ctx, imperal_id, sem, params.task_ids, params.task_titles, params.project_id,
    )

    rows = await _run_task_batch(
        ctx, refs, sem, "deleted",
        lambda tid: api_delete(ctx, f"/v1/tasks/{tid}", params={"imperal_id": imperal_id}),
    )

    # The stored contract for this tool calls the per-row flag `deleted`
    # (BulkDeleteItem), while the shared helper speaks in a neutral `ok`.
    # Translate rather than rename the model: the panel reads `deleted`.
    results = [
        {"task_id": r["task_id"], "title": r["title"], "deleted": r["ok"],
         **({"error": r["error"]} if r.get("error") else {})}
        for r in rows
    ]

    deleted_count = sum(1 for r in results if r["deleted"])
    failed_count = len(results) - deleted_count
    summary = f"Deleted {deleted_count} task(s)."
    if failed_count:
        summary += f" {failed_count} failed."

    return ActionResult.success(
        summary=summary,
        data={
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "results": results,
            "refresh_panels": ["sidebar", "editor"],
        },
    )


class CompleteTasksParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_ids: Optional[List[int]] = sdl.field(
        role="ref.target_id",
        description="List of integer task IDs to complete. Use this if you already have the IDs.",
        validation_alias=AliasChoices("task_ids", "message_ids", "ids"),
    )
    task_titles: Optional[List[str]] = Field(
        None,
        description="List of task titles to find and complete (e.g. ['Buy milk', 'Fix login bug']). Auto-resolved to task IDs.",
    )
    project_id: Optional[int] = Field(
        None,
        description="Narrow title search to a specific project. Recommended when using task_titles.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Project name to narrow title search (e.g. 'WebHostMost Tasks').",
    )


@chat.function(
    "complete_tasks",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="tasks.completed",
    description=(
        "Mark MULTIPLE tasks as done at once. Pass task_ids (list of integers) OR task_titles "
        "(list of names). When using task_titles, optionally pass project_name to narrow the "
        "search. Use when the user asks to complete/close 2+ tasks in one request."
    ),
    data_model=BulkTaskResult,
)
async def complete_tasks(ctx, params: CompleteTasksParams) -> ActionResult:
    """Complete a set of tasks concurrently, reported per task.

    The end-of-day case this exists for — "mark all of today's done" — was
    previously N separate calls. Non-destructive, so unlike the delete batch it
    needs no confirm gate: completing the wrong task is undone by
    uncomplete_task, which is why the ceiling and the per-item report are
    sufficient protection here.
    """
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if not params.task_ids and not params.task_titles:
        return ActionResult.error("Pass task_ids or task_titles.", code=VALIDATION_MISSING_FIELD)

    oversized = _check_batch_size((params.task_ids or []) + (params.task_titles or []), "tasks")
    if oversized:
        return oversized

    if params.project_name and not params.project_id:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    refs = await _resolve_task_refs(
        ctx, imperal_id, sem, params.task_ids, params.task_titles, params.project_id,
    )

    results = await _run_task_batch(
        ctx, refs, sem, "completed",
        lambda tid: api_post(
            ctx, f"/v1/tasks/{tid}",
            {"imperal_id": imperal_id, "done": True, "percent_done": 1.0},
        ),
    )

    succeeded = sum(1 for r in results if r["ok"])
    failed = len(results) - succeeded
    summary = f"Completed {succeeded} task(s)."
    if failed:
        summary += f" {failed} failed."

    return ActionResult.success(
        summary=summary,
        data={
            "succeeded_count": succeeded,
            "failed_count": failed,
            "results": results,
            "refresh_panels": ["sidebar", "editor"],
        },
    )


@chat.function(
    "create_subtask",
    action_type="write",
    chain_callable=True,
    id_projection="parent_task_id",
    effects=["create:task"],
    event="task.created",
    description="Create a subtask under a parent task. Returns the new subtask's task_id.",
    data_model=CreateSubtaskResult,
)
async def create_subtask(ctx, params: CreateSubtaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(ctx, f"/v1/tasks/{params.parent_task_id}/subtasks", {
        "imperal_id":  imperal_id,
        "title":       params.title,
        "description": params.description,
    })
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create subtask"), code=TASKS_BRIDGE_ERROR)

    return ActionResult.success(
        summary=f"Subtask created: {resp.get('title')}.",
        data={
            "subtask_id":     resp["id"],
            "parent_task_id": params.parent_task_id,
            "title":          resp["title"],
            "refresh_panels": ["sidebar", "editor"],
        },
    )


@chat.function(
    "list_subtasks",
    action_type="read",
    description="List all subtasks of a given task, including their done/pending status.",
    data_model=ListSubtasksResult,
)
async def list_subtasks(ctx, params: ListSubtasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, f"/v1/tasks/{params.task_id}/subtasks", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch subtasks"), code=TASKS_BRIDGE_ERROR)

    subtasks = resp if isinstance(resp, list) else []
    done_ct = sum(1 for s in subtasks if s.get("done"))
    return ActionResult.success(
        summary=f"Task #{params.task_id} has {len(subtasks)} subtask(s), {done_ct} done.",
        data={
            "items": [
                SubtaskItem(id=s["id"], title=s.get("title", "?"), kind="task", is_done=s.get("done", False)).model_dump()
                for s in subtasks
            ],
            "total":   len(subtasks),
            "task_id": params.task_id,
        },
    )


@chat.function(
    "toggle_checklist_item",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.updated",
    description=(
        "Check or uncheck a TipTap checklist item in a task description. "
        "Use item_index (0-based) from the visible checklist order."
    ),
    data_model=ToggleChecklistResult,
)
async def toggle_checklist_item(ctx, params: ToggleChecklistItemParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    task = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
    if isinstance(task, dict) and task.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(task, "Couldn't fetch task"), code=TASKS_BRIDGE_ERROR)

    desc = task.get("description") or ""
    new_desc = _toggle_checklist_item(desc, params.item_index, params.checked)
    if new_desc == desc:
        return ActionResult.error(
            f"Checklist item #{params.item_index} not found in task description.",
            code=TASKS_CHECKLIST_ITEM_NOT_FOUND,
        )

    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}", {
        "imperal_id": imperal_id,
        "description": new_desc,
    })
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update checklist item"), code=TASKS_BRIDGE_ERROR)

    state = "done" if params.checked else "unchecked"
    return ActionResult.success(
        summary=f"Checklist item #{params.item_index} marked {state}.",
        data={
            "task_id":    params.task_id,
            "item_index": params.item_index,
            "checked":    params.checked,
            "refresh_panels": ["editor"],
        },
    )


class GetTaskParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")


@chat.function(
    "get_task",
    action_type="read",
    description=(
        "Get full details of a single task by ID: title, description, done status, "
        "due date, priority, assignees, labels, and project. "
        "Use this to verify task state before updating, or when user asks about a specific task."
    ),
    data_model=TaskEntity,
)
async def get_task(ctx, params: GetTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch task"), code=TASKS_BRIDGE_ERROR)

    t = resp
    entity = TaskEntity(
        id=t.get("id"),
        title=t.get("title", "") or f"Task #{params.task_id}",
        kind="task",
        description=t.get("description") or None,
        is_done=t.get("done", False),
        priority=vikunja_priority(t.get("priority", 0)),
        due_at=vikunja_date(t.get("due_date")),
        start_at=vikunja_date(t.get("start_date")),
        created_at=vikunja_date(t.get("created")),
        updated_at=vikunja_date(t.get("updated")),
        percent_done=t.get("percent_done", 0.0),
        project_id=t.get("project_id"),
        bucket_id=t.get("bucket_id") or None,
        hex_color=t.get("hex_color") or None,
        is_favorite=t.get("is_favorite", False),
        assignees=[
            TaskAssignee(vikunja_user_id=a.get("id"), username=a.get("username", ""))
            for a in (t.get("assignees") or [])
        ],
        labels=[
            TaskLabelItem(label_id=l.get("id"), title=l.get("title", ""), hex_color=l.get("hex_color"))
            for l in (t.get("labels") or [])
        ],
    )
    status = "done" if entity.is_done else "open"
    return ActionResult.success(
        summary=f"Task '{entity.title}' (id={entity.id}) — {status}",
        data=entity,
    )
