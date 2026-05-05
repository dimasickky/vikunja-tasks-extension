"""tasks · Organize operations (assign, label, due, priority, move)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, chat
from handlers_crud import (
    _require_user,
    _update_task_impl,
    _bridge_error_msg,
    UpdateTaskParams,
)


class AssignTaskParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID from a prior list_my_tasks/filter_tasks/create_task response. Never UUID.")
    assignee_vikunja_user_id: int = Field(
        ...,
        description=(
            "Integer Vikunja user ID (from Vikunja's users table). NOT imperal_id, NOT username, NOT email. "
            "Obtain via list_comments (author objects) or by asking the user for their numeric Vikunja user id."
        ),
    )


class UnassignTaskParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    assignee_vikunja_user_id: int = Field(..., description="Integer Vikunja user ID (same one used in assign_task).")


class AddLabelParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    label_id: int = Field(..., description="Integer label ID — obtain via create_label response or Vikunja UI. Never label name.")


class DetachLabelParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    label_id: int = Field(..., description="Integer label ID currently attached to this task.")


class SetDueDateParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    due_date: str = Field(..., description="ISO 8601 UTC string, e.g. '2026-04-25T12:00:00Z'.")


class SetPriorityParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    priority: int = Field(..., ge=0, le=5, description="0=none, 1=low, 2=medium, 3=high, 4=urgent, 5=critical.")


class MoveToProjectParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    project_id: int = Field(..., description="Integer project ID from list_projects response. Never project name.")


class MoveToBucketParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    bucket_id: int = Field(..., description="Integer bucket ID from list_buckets response. Never bucket name.")


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
    description=(
        "Assign a Vikunja user (by integer Vikunja user ID) to a task. "
        "If the user gave a username or email, ask them for their numeric Vikunja user ID first — "
        "we don't have a list_users endpoint."
    ),
)
async def assign_task(ctx, params: AssignTaskParams) -> ActionResult:
    return await _assign_task_impl(ctx, params)


@chat.function(
    "unassign_task",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="task.unassigned",
    description="Remove a Vikunja user (by integer user ID) from a task's assignee list.",
)
async def unassign_task(ctx, params: UnassignTaskParams) -> ActionResult:
    return await _unassign_task_impl(ctx, params)


@chat.function(
    "add_label",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.labeled",
    description=(
        "Attach an existing label (by integer label_id) to a task (by integer task_id). "
        "If you only know the label name, call create_label or ask the user for the numeric label_id — "
        "Vikunja addresses labels by ID, never by name."
    ),
)
async def add_label(ctx, params: AddLabelParams) -> ActionResult:
    return await _add_label_impl(ctx, params)


@chat.function(
    "remove_label",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.unlabeled",
    description="Detach a label (by integer label_id) from a task (by integer task_id).",
)
async def remove_label(ctx, params: DetachLabelParams) -> ActionResult:
    return await _detach_label_impl(ctx, params)


@chat.function(
    "set_due_date",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.due_changed",
    description=(
        "Set or change due date of a task. Pass integer task_id and due_date as ISO 8601 UTC string "
        "(e.g. '2026-04-25T12:00:00Z'). Convert relative dates ('Friday', 'tomorrow') in user's timezone first."
    ),
)
async def set_due_date(ctx, params: SetDueDateParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, due_date=params.due_date))


@chat.function(
    "set_priority",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.priority_changed",
    description="Set task priority — integer 0 (none) to 5 (critical). Pass integer task_id.",
)
async def set_priority(ctx, params: SetPriorityParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, priority=params.priority))


@chat.function(
    "move_to_project",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.moved",
    description=(
        "Move a task to another project. Pass integer task_id and integer project_id "
        "(from list_projects response — never project name)."
    ),
)
async def move_to_project(ctx, params: MoveToProjectParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, project_id=params.project_id))


@chat.function(
    "move_to_bucket",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.bucket_changed",
    description=(
        "Move a task to another kanban bucket (column). Pass integer task_id and integer bucket_id "
        "(from list_buckets response — never bucket name). Call list_buckets first if bucket_id is unknown."
    ),
)
async def move_to_bucket(ctx, params: MoveToBucketParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, bucket_id=params.bucket_id))
