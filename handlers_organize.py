"""tasks · Organize operations (assign, label, due, priority, move).

Some ops are thin specialisations of _update_task_impl (single-field update).
assign_task and add_label use dedicated bridge endpoints.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, chat
from handlers_crud import (
    _require_user,
    _update_task_impl,
    UpdateTaskParams,
)


# ─── Params ────────────────────────────────────────────────────────────── #

class AssignTaskParams(BaseModel):
    task_id: int
    assignee_vikunja_user_id: int = Field(..., description="Vikunja user id — from users table.")


class UnassignTaskParams(BaseModel):
    task_id: int
    assignee_vikunja_user_id: int


class AddLabelParams(BaseModel):
    task_id: int
    label_id: int


class DetachLabelParams(BaseModel):
    task_id: int
    label_id: int


class SetDueDateParams(BaseModel):
    task_id: int
    due_date: str = Field(..., description="ISO 8601 (e.g. 2026-04-25T12:00:00Z).")


class SetPriorityParams(BaseModel):
    task_id: int
    priority: int = Field(..., ge=0, le=5, description="0=none, 1=low, 2=medium, 3=high, 4=urgent, 5=critical.")


class MoveToProjectParams(BaseModel):
    task_id: int
    project_id: int


class MoveToBucketParams(BaseModel):
    task_id: int
    bucket_id: int


# ─── Impl ──────────────────────────────────────────────────────────────── #

async def _assign_task_impl(ctx, params: AssignTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        f"/v1/tasks/{params.task_id}/assign",
        {"imperal_id": imperal_id, "assignee_vikunja_user_id": params.assignee_vikunja_user_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось назначить: {resp.get('detail')}")
    return ActionResult.success(
        message=f"Назначил юзера {params.assignee_vikunja_user_id} на таск #{params.task_id}.",
        data={"task_id": params.task_id, "assignee_vikunja_user_id": params.assignee_vikunja_user_id},
    )


async def _unassign_task_impl(ctx, params: UnassignTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        f"/v1/tasks/{params.task_id}/assign/{params.assignee_vikunja_user_id}",
        params={"imperal_id": imperal_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось снять назначение: {resp.get('detail')}")
    return ActionResult.success(
        message=f"Снял назначение юзера {params.assignee_vikunja_user_id} с таска #{params.task_id}.",
        data={"task_id": params.task_id, "assignee_vikunja_user_id": params.assignee_vikunja_user_id},
    )


async def _add_label_impl(ctx, params: AddLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        f"/v1/tasks/{params.task_id}/labels",
        {"imperal_id": imperal_id, "label_id": params.label_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось прикрепить метку: {resp.get('detail')}")
    return ActionResult.success(
        message=f"Прикрепил метку #{params.label_id} к таску #{params.task_id}.",
        data={"task_id": params.task_id, "label_id": params.label_id},
    )


async def _detach_label_impl(ctx, params: DetachLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        f"/v1/tasks/{params.task_id}/labels/{params.label_id}",
        params={"imperal_id": imperal_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось открепить метку: {resp.get('detail')}")
    return ActionResult.success(
        message=f"Открепил метку #{params.label_id} от таска #{params.task_id}.",
        data={"task_id": params.task_id, "label_id": params.label_id},
    )


async def _set_due_date_impl(ctx, params: SetDueDateParams) -> ActionResult:
    return await _update_task_impl(
        ctx, UpdateTaskParams(task_id=params.task_id, due_date=params.due_date),
    )


async def _set_priority_impl(ctx, params: SetPriorityParams) -> ActionResult:
    return await _update_task_impl(
        ctx, UpdateTaskParams(task_id=params.task_id, priority=params.priority),
    )


async def _move_to_project_impl(ctx, params: MoveToProjectParams) -> ActionResult:
    return await _update_task_impl(
        ctx, UpdateTaskParams(task_id=params.task_id, project_id=params.project_id),
    )


async def _move_to_bucket_impl(ctx, params: MoveToBucketParams) -> ActionResult:
    return await _update_task_impl(
        ctx, UpdateTaskParams(task_id=params.task_id, bucket_id=params.bucket_id),
    )


# ─── @chat.function wrappers ───────────────────────────────────────────── #

@chat.function(
    "assign_task",
    action_type="write",
    event="task.assigned",
    description="Assign a Vikunja user as assignee to a task.",
)
async def assign_task(ctx, params: AssignTaskParams) -> ActionResult:
    return await _assign_task_impl(ctx, params)


@chat.function(
    "unassign_task",
    action_type="write",
    event="task.unassigned",
    description="Remove a Vikunja user from task assignees.",
)
async def unassign_task(ctx, params: UnassignTaskParams) -> ActionResult:
    return await _unassign_task_impl(ctx, params)


@chat.function(
    "add_label",
    action_type="write",
    event="task.labeled",
    description="Attach an existing label to a task.",
)
async def add_label(ctx, params: AddLabelParams) -> ActionResult:
    return await _add_label_impl(ctx, params)


@chat.function(
    "remove_label",
    action_type="write",
    event="task.unlabeled",
    description="Detach a label from a task.",
)
async def remove_label(ctx, params: DetachLabelParams) -> ActionResult:
    return await _detach_label_impl(ctx, params)


@chat.function(
    "set_due_date",
    action_type="write",
    event="task.due_changed",
    description="Set or change due date of a task. Use ISO 8601 UTC.",
)
async def set_due_date(ctx, params: SetDueDateParams) -> ActionResult:
    return await _set_due_date_impl(ctx, params)


@chat.function(
    "set_priority",
    action_type="write",
    event="task.priority_changed",
    description="Set priority 0 (none) to 5 (critical).",
)
async def set_priority(ctx, params: SetPriorityParams) -> ActionResult:
    return await _set_priority_impl(ctx, params)


@chat.function(
    "move_to_project",
    action_type="write",
    event="task.moved",
    description="Move a task to another project.",
)
async def move_to_project(ctx, params: MoveToProjectParams) -> ActionResult:
    return await _move_to_project_impl(ctx, params)


@chat.function(
    "move_to_bucket",
    action_type="write",
    event="task.bucket_changed",
    description="Move a task to another kanban bucket (column).",
)
async def move_to_bucket(ctx, params: MoveToBucketParams) -> ActionResult:
    return await _move_to_bucket_impl(ctx, params)
