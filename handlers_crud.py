"""tasks · CRUD lifecycle functions (create / update / complete / delete).

Each business op has a private `_impl` function that holds the single source
of truth, plus a `@chat.function` wrapper (billable via Webbee / automation)
and a `@ext.panel` wrapper in handlers_panel.py (FREE via TD15).
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, chat, _imperal_id


# ─── Params ────────────────────────────────────────────────────────────── #

class CreateTaskParams(BaseModel):
    project_id: int = Field(..., description="Project (board) to create task in.")
    title: str = Field(..., min_length=1, max_length=250, description="Task title.")
    description: str = Field("", description="Optional description, markdown.")
    due_date: Optional[str] = Field(None, description="ISO 8601 due date (e.g. 2026-04-25T12:00:00Z).")
    priority: Optional[int] = Field(None, ge=0, le=5, description="0=none, 5=urgent.")
    bucket_id: Optional[int] = Field(None, description="Kanban bucket; default = first bucket of project.")


class UpdateTaskParams(BaseModel):
    task_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0, le=5)
    percent_done: Optional[float] = Field(None, ge=0.0, le=1.0)
    bucket_id: Optional[int] = None
    project_id: Optional[int] = Field(None, description="Move to another project.")
    hex_color: Optional[str] = None


class CompleteTaskParams(BaseModel):
    task_id: int


class DeleteTaskParams(BaseModel):
    task_id: int


# ─── Impl functions (single source of truth) ───────────────────────────── #

def _require_user(ctx) -> str | ActionResult:
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return ActionResult.error("Нет контекста пользователя — provisioning не выполнен.")
    return imperal_id


async def _create_task_impl(ctx, params: CreateTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {
        "imperal_id": imperal_id,
        "project_id": params.project_id,
        "title": params.title,
        "description": params.description,
    }
    if params.due_date is not None:
        payload["due_date"] = params.due_date
    if params.priority is not None:
        payload["priority"] = params.priority
    if params.bucket_id is not None:
        payload["bucket_id"] = params.bucket_id

    resp = await api_post("/v1/tasks", payload)
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось создать таск: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Создал таск «{resp['title']}» в проекте #{resp['project_id']}.",
        data={
            "task_id": resp["id"],
            "title": resp["title"],
            "project_id": resp["project_id"],
            "due_date": resp.get("due_date"),
            "priority": resp.get("priority", 0),
            "bucket_id": resp.get("bucket_id", 0),
        },
    )


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
        return ActionResult.error("Нет полей для обновления — передай хотя бы одно поле.")

    resp = await api_post(f"/v1/tasks/{params.task_id}", payload)
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось обновить таск: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Обновил таск «{resp.get('title', params.task_id)}».",
        data={
            "task_id": resp.get("id", params.task_id),
            "title": resp.get("title"),
            "done": resp.get("done", False),
            "due_date": resp.get("due_date"),
            "priority": resp.get("priority", 0),
            "percent_done": resp.get("percent_done", 0.0),
        },
    )


async def _complete_task_impl(ctx, params: CompleteTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        f"/v1/tasks/{params.task_id}",
        {"imperal_id": imperal_id, "done": True, "percent_done": 1.0},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось закрыть таск: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Закрыл таск «{resp.get('title', params.task_id)}».",
        data={"task_id": resp.get("id", params.task_id), "done": True},
    )


async def _delete_task_impl(ctx, params: DeleteTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        f"/v1/tasks/{params.task_id}",
        params={"imperal_id": imperal_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось удалить таск: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Удалил таск #{params.task_id}.",
        data={"task_id": params.task_id, "deleted": True},
    )


# ─── @chat.function wrappers (billable — LLM/automation surface) ───────── #

@chat.function(
    "create_task",
    action_type="write",
    event="task.created",
    description="Create a new task in a project. Returns task_id + full task details.",
)
async def create_task(ctx, params: CreateTaskParams) -> ActionResult:
    return await _create_task_impl(ctx, params)


@chat.function(
    "update_task",
    action_type="write",
    event="task.updated",
    description="Update any fields of a task (title, description, due_date, priority, percent_done, bucket, etc.).",
)
async def update_task(ctx, params: UpdateTaskParams) -> ActionResult:
    return await _update_task_impl(ctx, params)


@chat.function(
    "complete_task",
    action_type="write",
    event="task.completed",
    description="Mark a task as done (done=true, percent_done=1.0).",
)
async def complete_task(ctx, params: CompleteTaskParams) -> ActionResult:
    return await _complete_task_impl(ctx, params)


@chat.function(
    "delete_task",
    action_type="destructive",
    event="task.deleted",
    description="Permanently delete a task. Cannot be undone.",
)
async def delete_task(ctx, params: DeleteTaskParams) -> ActionResult:
    return await _delete_task_impl(ctx, params)
