"""tasks · Organize operations (assign, label, due, priority, move)."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, chat, is_no_connection_error
from handlers_crud import (
    _require_user,
    _update_task_impl,
    _bridge_error_msg,
    UpdateTaskParams,
)


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


# ─── Impl ─────────────────────────────────────────────────────────────────── #

async def _assign_task_impl(ctx, params: AssignTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id
    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}/assign",
                          {"imperal_id": imperal_id, "assignee_vikunja_user_id": params.assignee_vikunja_user_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't assign user"))
    return ActionResult.success(
        summary=f"Assigned user {params.assignee_vikunja_user_id} to task #{params.task_id}.",
        data={"task_id": params.task_id, "assignee_vikunja_user_id": params.assignee_vikunja_user_id,
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _unassign_task_impl(ctx, params: UnassignTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id
    resp = await api_delete(ctx, f"/v1/tasks/{params.task_id}/assign/{params.assignee_vikunja_user_id}",
                            params={"imperal_id": imperal_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't unassign user"))
    return ActionResult.success(
        summary=f"Unassigned user {params.assignee_vikunja_user_id} from task #{params.task_id}.",
        data={"task_id": params.task_id, "assignee_vikunja_user_id": params.assignee_vikunja_user_id,
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _add_label_impl(ctx, params: AddLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id
    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}/labels",
                          {"imperal_id": imperal_id, "label_id": params.label_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't attach label"))
    return ActionResult.success(
        summary=f"Attached label #{params.label_id} to task #{params.task_id}.",
        data={"task_id": params.task_id, "label_id": params.label_id, "refresh_panels": ["sidebar", "editor"]},
    )


async def _detach_label_impl(ctx, params: DetachLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id
    resp = await api_delete(ctx, f"/v1/tasks/{params.task_id}/labels/{params.label_id}",
                            params={"imperal_id": imperal_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't detach label"))
    return ActionResult.success(
        summary=f"Detached label #{params.label_id} from task #{params.task_id}.",
        data={"task_id": params.task_id, "label_id": params.label_id, "refresh_panels": ["sidebar", "editor"]},
    )


# ─── @chat.function wrappers ──────────────────────────────────────────────── #

@chat.function(
    "assign_task",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.assigned",
    description="Assign a Vikunja user as assignee to a task.",
)
async def assign_task(ctx, params: AssignTaskParams) -> ActionResult:
    return await _assign_task_impl(ctx, params)


@chat.function(
    "unassign_task",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.unassigned",
    description="Remove a Vikunja user from task assignees.",
)
async def unassign_task(ctx, params: UnassignTaskParams) -> ActionResult:
    return await _unassign_task_impl(ctx, params)


@chat.function(
    "add_label",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.labeled",
    description="Attach an existing label to a task.",
)
async def add_label(ctx, params: AddLabelParams) -> ActionResult:
    return await _add_label_impl(ctx, params)


@chat.function(
    "remove_label",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.unlabeled",
    description="Detach a label from a task.",
)
async def remove_label(ctx, params: DetachLabelParams) -> ActionResult:
    return await _detach_label_impl(ctx, params)


@chat.function(
    "set_due_date",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.due_changed",
    description="Set or change due date of a task. Use ISO 8601 UTC.",
)
async def set_due_date(ctx, params: SetDueDateParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, due_date=params.due_date))


@chat.function(
    "set_priority",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.priority_changed",
    description="Set priority 0 (none) to 5 (critical).",
)
async def set_priority(ctx, params: SetPriorityParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, priority=params.priority))


@chat.function(
    "move_to_project",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.moved",
    description="Move a task to another project.",
)
async def move_to_project(ctx, params: MoveToProjectParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, project_id=params.project_id))


@chat.function(
    "move_to_bucket",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.bucket_changed",
    description="Move a task to another kanban bucket (column).",
)
async def move_to_bucket(ctx, params: MoveToBucketParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, bucket_id=params.bucket_id))
