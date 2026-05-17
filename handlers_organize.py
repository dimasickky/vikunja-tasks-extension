"""tasks · Organize operations (assign, label, due, priority, move)."""

from typing import Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_get, api_delete, chat
from handlers_crud import (
    _require_user,
    _update_task_impl,
    _bridge_error_msg,
    UpdateTaskParams,
)
from models_return import (
    SearchUsersResult,
    AssignResult,
    UnassignResult,
    TaskLabelResult,
    UpdateTaskResult,
)


class SearchUsersParams(BaseModel):
    query: str = Field(
        "",
        description=(
            "Name or email fragment to search for (e.g. 'val', 'ignat', 'denis@'). "
            "Pass empty string to list all known users on this Vikunja instance."
        ),
    )


class AssignTaskParams(BaseModel):
    task_id: int = Field(
        0,
        description=(
            "Integer task ID. Pass 0 if you only know the task by name — "
            "task_name will be used to auto-resolve it."
        ),
    )
    task_name: Optional[str] = Field(
        None,
        description=(
            "Task title to search for when task_id is unknown. "
            "The first matching task is used — prefer find_task first for disambiguation."
        ),
    )
    assignee_query: str = Field(
        ...,
        description=(
            "Name or email of the person to assign (e.g. 'Val', 'val@webhostmost.com'). "
            "The bridge resolves it to a Vikunja user ID automatically."
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

async def _search_users_impl(ctx, params: SearchUsersParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, "/v1/users", {"imperal_id": imperal_id, "s": params.query})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't search users"))

    users = resp if isinstance(resp, list) else []
    if not users:
        msg = f"No users found matching '{params.query}'." if params.query else "No other users found on this Vikunja instance."
        return ActionResult.success(summary=msg, data={"users": []})

    lines = []
    for u in users:
        tag = " ✓" if u.get("connected") else ""
        lines.append(f"• {u['username']} (ID: {u['id']}){tag}")

    label = f"matching '{params.query}'" if params.query else "on this Vikunja instance"
    return ActionResult.success(
        summary=f"Found {len(users)} user(s) {label}:\n" + "\n".join(lines),
        data={"users": users},
    )


async def _assign_task_impl(ctx, params: AssignTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    task_id = params.task_id
    if task_id == 0 and params.task_name:
        search_resp = await api_get(ctx, "/v1/tasks/all", {
            "imperal_id": imperal_id, "s": params.task_name, "per_page": 5,
        })
        tasks = search_resp if isinstance(search_resp, list) else []
        if not tasks:
            return ActionResult.error(
                f"Task '{params.task_name}' not found. "
                "Call find_task(query=...) to search and get the integer task_id first."
            )
        if len(tasks) > 1:
            matches = ", ".join(f"#{t['id']} '{t.get('title', '?')}'" for t in tasks[:3])
            return ActionResult.error(
                f"Multiple tasks match '{params.task_name}': {matches}. "
                "Pass task_id directly to avoid assigning the wrong task."
            )
        task_id = tasks[0]["id"]

    if not task_id:
        return ActionResult.error(
            "task_id is required. Call find_task(query=...) first to resolve the task name to an integer task_id."
        )

    resp = await api_post(ctx, f"/v1/tasks/{task_id}/assign",
                          {"imperal_id": imperal_id, "assignee_query": params.assignee_query})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't assign user"))
    resolved_id = resp.get("_resolved_user_id")
    resolved_name = resp.get("_resolved_username", params.assignee_query)
    return ActionResult.success(
        summary=f"Assigned {resolved_name} to task #{task_id}.",
        data={"task_id": task_id, "assignee_vikunja_user_id": resolved_id,
              "assignee_name": resolved_name, "refresh_panels": ["sidebar", "editor"]},
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
    id_projection="task_id",
    effects=["update:task"],
    event="task.assigned",
    description=(
        "Assign a person to a task by their name or email address (e.g. 'Val' or 'val@webhostmost.com'). "
        "The bridge resolves the name/email to a Vikunja user ID automatically — never ask for a numeric ID."
    ),
    data_model=AssignResult,
)
async def assign_task(ctx, params: AssignTaskParams) -> ActionResult:
    return await _assign_task_impl(ctx, params)


@chat.function(
    "unassign_task",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.unassigned",
    description="Remove a Vikunja user (by integer user ID) from a task's assignee list.",
    data_model=UnassignResult,
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
    data_model=TaskLabelResult,
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
    data_model=TaskLabelResult,
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
    data_model=UpdateTaskResult,
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
    data_model=UpdateTaskResult,
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
    data_model=UpdateTaskResult,
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
    data_model=UpdateTaskResult,
)
async def move_to_bucket(ctx, params: MoveToBucketParams) -> ActionResult:
    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, bucket_id=params.bucket_id))


@chat.function(
    "search_vikunja_users",
    action_type="read",
    chain_callable=False,
    effects=[],
    description=(
        "Search for Vikunja users by name or email fragment — use this before assign_task "
        "to discover who is available, or when the user asks who they can assign tasks to. "
        "Pass empty query to list all known users on the Vikunja instance."
    ),
    data_model=SearchUsersResult,
)
async def search_vikunja_users(ctx, params: SearchUsersParams) -> ActionResult:
    return await _search_users_impl(ctx, params)
