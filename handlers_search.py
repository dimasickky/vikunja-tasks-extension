"""tasks · Read-only search / list operations.

Uses Vikunja's native filter syntax via /api/v1/tasks/all passthrough.
Filter grammar: `done = false && due_date < now + 7d && priority >= 3` etc.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, chat
from handlers_crud import _require_user


# ─── Params ────────────────────────────────────────────────────────────── #

class ListMyTasksParams(BaseModel):
    filter: Optional[str] = Field(
        None,
        description="Vikunja filter syntax, e.g. 'done = false && project_id = 5'.",
    )
    sort_by: Optional[str] = Field(
        None,
        description="Field name; prefix with '-' for desc, e.g. 'due_date' or '-priority'.",
    )
    search: Optional[str] = Field(None, description="Free-text search in title/description.")
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=200)


class FilterTasksParams(BaseModel):
    filter: str = Field(..., description="Vikunja filter expression (required).")
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=200)


# ─── Impl ──────────────────────────────────────────────────────────────── #

def _summarise_tasks(tasks: list[dict], limit: int = 10) -> str:
    """Human-readable one-line summary for ActionResult.message."""
    if not tasks:
        return "Тасков нет."
    if len(tasks) == 1:
        return f"1 таск: «{tasks[0].get('title', '?')}»."
    titles = [t.get("title", "?") for t in tasks[:limit]]
    more = f" + ещё {len(tasks) - limit}" if len(tasks) > limit else ""
    return f"{len(tasks)} тасков: {', '.join(f'«{x}»' for x in titles)}{more}."


async def _list_my_tasks_impl(ctx, params: ListMyTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    q: dict = {"imperal_id": imperal_id, "page": params.page, "per_page": params.per_page}
    if params.filter:
        q["filter"] = params.filter
    if params.sort_by:
        q["sort_by"] = params.sort_by
    if params.search:
        q["s"] = params.search

    resp = await api_get("/v1/tasks/all", q)
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(f"Не удалось получить таски: {resp.get('detail')}")

    tasks = resp if isinstance(resp, list) else []
    return ActionResult.success(
        message=_summarise_tasks(tasks),
        data={
            "count": len(tasks),
            "tasks": [
                {
                    "task_id": t["id"],
                    "title": t["title"],
                    "project_id": t.get("project_id"),
                    "done": t.get("done", False),
                    "due_date": t.get("due_date"),
                    "priority": t.get("priority", 0),
                }
                for t in tasks
            ],
        },
    )


async def _list_overdue_impl(ctx, _params: BaseModel) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx, ListMyTasksParams(filter="done = false && due_date < now", sort_by="due_date"),
    )


async def _list_today_impl(ctx, _params: BaseModel) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx,
        ListMyTasksParams(
            filter="done = false && due_date >= now/d && due_date < now/d+1d",
            sort_by="priority",
        ),
    )


async def _filter_tasks_impl(ctx, params: FilterTasksParams) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx,
        ListMyTasksParams(filter=params.filter, page=params.page, per_page=params.per_page),
    )


# ─── @chat.function wrappers ───────────────────────────────────────────── #

class _NoParams(BaseModel):
    pass


@chat.function(
    "list_my_tasks",
    action_type="read",
    description=(
        "List tasks with optional Vikunja filter syntax. "
        "Examples: `done = false`, `priority >= 3 && due_date < now + 7d`."
    ),
)
async def list_my_tasks(ctx, params: ListMyTasksParams) -> ActionResult:
    return await _list_my_tasks_impl(ctx, params)


@chat.function(
    "list_overdue",
    action_type="read",
    description="List all overdue tasks (done=false AND due_date in the past).",
)
async def list_overdue(ctx, params: _NoParams) -> ActionResult:
    return await _list_overdue_impl(ctx, params)


@chat.function(
    "list_today",
    action_type="read",
    description="List tasks due today (done=false AND due_date between start-of-day and end-of-day).",
)
async def list_today(ctx, params: _NoParams) -> ActionResult:
    return await _list_today_impl(ctx, params)


@chat.function(
    "filter_tasks",
    action_type="read",
    description=(
        "Filter tasks with Vikunja expression. Operators: = != > < >= <= in like. "
        "Logical: && ||. Time helpers: now, now/d, now+7d, now-3d. "
        "Fields: title, description, done, due_date, start_date, end_date, priority, project_id, percent_done."
    ),
)
async def filter_tasks(ctx, params: FilterTasksParams) -> ActionResult:
    return await _filter_tasks_impl(ctx, params)
