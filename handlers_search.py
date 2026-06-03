"""tasks · Read-only search / list operations."""

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, chat, NoParams, fetch_all_pages
from handlers_crud import _require_user, _bridge_error_msg
from models_return import TaskListResult, FindTaskResult, TaskItem, vikunja_priority, vikunja_date


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
    filter: Optional[str] = Field(
        None,
        description=(
            "Vikunja filter expression, e.g. 'done = false && project_id = 5'. "
            "If omitted, returns ALL tasks (no filter applied). "
            "NOTE: bucket_id is not a valid filter field — use list_buckets instead."
        ),
    )
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=200)


def _summarise_tasks(tasks: list[dict], limit: int = 10) -> str:
    if not tasks:
        return "No tasks."
    if len(tasks) == 1:
        return f"1 task: {tasks[0].get('title', '?')}."
    titles = [t.get("title", "?") for t in tasks[:limit]]
    more = f" + {len(tasks) - limit} more" if len(tasks) > limit else ""
    return f"{len(tasks)} tasks: {', '.join(titles)}{more}."


async def _list_my_tasks_impl(ctx, params: ListMyTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    base: dict = {"imperal_id": imperal_id}
    if params.filter:   base["filter"] = params.filter
    if params.sort_by:  base["sort_by"] = params.sort_by
    if params.search:   base["s"] = params.search

    # Auto-paginate when using default page=1 to return all tasks, not just first 50.
    if params.page == 1:
        tasks = await fetch_all_pages(ctx, base)
        if not tasks:
            resp = await api_get(ctx, "/v1/tasks/all", {**base, "page": 1, "per_page": 50})
            if isinstance(resp, dict) and resp.get("status") == "error":
                return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch tasks"))
    else:
        q = {**base, "page": params.page, "per_page": params.per_page}
        resp = await api_get(ctx, "/v1/tasks/all", q)
        if isinstance(resp, dict) and resp.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch tasks"))
        tasks = resp if isinstance(resp, list) else []
    items = [
        TaskItem(
            id=t["id"],
            title=t.get("title", "?"),
            kind="task",
            is_done=t.get("done", False),
            priority=vikunja_priority(t.get("priority", 0)),
            due_at=vikunja_date(t.get("due_date")),
            project_id=t.get("project_id"),
        ).model_dump()
        for t in tasks
    ]
    return ActionResult.success(
        summary=_summarise_tasks(tasks),
        data={"items": items, "total": len(items)},
    )


@chat.function(
    "list_my_tasks",
    action_type="read",
    description=(
        "List tasks with optional Vikunja filter syntax. "
        "Examples: `done = false`, `priority >= 3 && due_date < now + 7d`."
    ),
    data_model=TaskListResult,
)
async def list_my_tasks(ctx, params: ListMyTasksParams) -> ActionResult:
    return await _list_my_tasks_impl(ctx, params)


@chat.function(
    "list_overdue",
    action_type="read",
    description="List all overdue tasks (done=false AND due_date in the past).",
    data_model=TaskListResult,
)
async def list_overdue(ctx, params: NoParams) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx, ListMyTasksParams(filter="done = false && due_date < now", sort_by="due_date"),
    )


@chat.function(
    "list_today",
    action_type="read",
    description="List tasks due today (done=false AND due_date between start-of-day and end-of-day).",
    data_model=TaskListResult,
)
async def list_today(ctx, params: NoParams) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx, ListMyTasksParams(
            filter="done = false && due_date >= now/d && due_date < now/d+1d",
            sort_by="priority",
        ),
    )


@chat.function(
    "list_upcoming",
    action_type="read",
    description="List tasks due in the next 7 days (done=false AND due_date between now and now+7d).",
    data_model=TaskListResult,
)
async def list_upcoming(ctx, params: NoParams) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx, ListMyTasksParams(
            filter="done = false && due_date >= now && due_date < now+7d",
            sort_by="due_date",
        ),
    )


class FindTaskParams(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description=(
            "Substring of task title to search for. Returns matching tasks with "
            "their integer task_id, project_id, bucket_id."
        ),
    )


@chat.function(
    "find_task",
    action_type="read",
    description=(
        "Search tasks by title substring. Returns matching tasks with their "
        "integer task_id and project_id. Call this first when the user mentions "
        "a task by name and you don't have its integer ID — never invent task_id."
    ),
    data_model=FindTaskResult,
)
async def find_task(ctx, params: FindTaskParams) -> ActionResult:
    result = await _list_my_tasks_impl(
        ctx, ListMyTasksParams(search=params.query, per_page=20),
    )
    if result.status != "success":
        return result

    items = (result.data or {}).get("items", []) if isinstance(result.data, dict) else []
    n = len(items)
    if n == 0:
        summary = f"No tasks found matching '{params.query}'."
    else:
        preview = ", ".join(f"{t.get('title', '?')} (#{t.get('id')})" for t in items[:5])
        more = f" + {n - 5} more" if n > 5 else ""
        summary = f"Found {n} task(s) matching '{params.query}': {preview}{more}."

    return ActionResult.success(
        summary=summary,
        data={"items": items, "total": n, "query": params.query},
    )


@chat.function(
    "filter_tasks",
    action_type="read",
    description=(
        "Filter tasks with Vikunja expression. Operators: = != > < >= <= in like. "
        "Logical: && ||. Time helpers: now, now/d, now+7d, now-3d. "
        "Fields: title, description, done, due_date, start_date, end_date, priority, project_id, percent_done."
    ),
    data_model=TaskListResult,
)
async def filter_tasks(ctx, params: FilterTasksParams) -> ActionResult:
    return await _list_my_tasks_impl(
        ctx, ListMyTasksParams(
            filter=params.filter,  # None = no filter = all tasks
            page=params.page,
            per_page=params.per_page,
        ),
    )
