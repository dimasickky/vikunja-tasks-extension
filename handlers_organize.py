"""tasks · Organize operations (assign, label, due, priority, move)."""

from typing import Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

import logging

from app import api_post, api_get, api_delete, chat, resolve_project_id
from handlers_crud import (
    _require_user,
    _update_task_impl,
    _bridge_error_msg,
    UpdateTaskParams,
)
from models_return import (
    SearchUsersResult,
    ProjectMembersResult,
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


class ListProjectMembersParams(BaseModel):
    project_id: Optional[int] = Field(
        None,
        description="Integer project ID. Pass project_name instead if you only know the name.",
    )
    project_name: Optional[str] = Field(
        None,
        description=(
            "Project title to resolve (e.g. 'WebHostMost Tasks'). Used when project_id is unknown. "
            "Case-insensitive."
        ),
    )


class AssignTaskParams(BaseModel):
    task_id: int = Field(
        0,
        description=(
            "Integer task ID. Pass 0 when you only know the task by name — "
            "task_name will be used to auto-resolve it. Do NOT call find_task first."
        ),
    )
    task_name: Optional[str] = Field(
        None,
        description=(
            "Task title to search for when task_id is unknown. "
            "Call assign_task directly with task_name — do NOT pre-search with find_task. "
            "If multiple tasks share the same name, also pass bucket_name to disambiguate."
        ),
    )
    bucket_name: Optional[str] = Field(
        None,
        description=(
            "Bucket/column name to disambiguate when multiple tasks share the same title "
            "(e.g. 'the team'). Case-insensitive. Used only when task_name is set."
        ),
    )
    assignee_query: str = Field(
        ...,
        description=(
            "Name or email of the person to assign (e.g. 'ignat', 'ignat@webhostmost.com'). "
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


log = logging.getLogger("tasks")


class MoveToProjectParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    project_id: Optional[int] = Field(None, description="Integer project ID. Pass project_name instead if unknown.")
    project_name: Optional[str] = Field(None, description="Project name to look up (e.g. 'webhostmost tasks').")


class MoveToBucketParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    bucket_id: Optional[int] = Field(
        None,
        description="Integer bucket ID from list_buckets response. Pass bucket_name + project_name instead if unknown.",
    )
    bucket_name: Optional[str] = Field(
        None,
        description="Bucket name (e.g. 'To-Do', 'In Progress'). Used when bucket_id unknown.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Project name — needed to resolve bucket_name to bucket_id.",
    )


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


async def _list_project_members_impl(ctx, params: ListProjectMembersParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    project_id = params.project_id
    if project_id is None and params.project_name:
        project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if project_id is None:
            return ActionResult.error(f"No project found matching '{params.project_name}'.")
    if project_id is None:
        return ActionResult.error("Pass project_id or project_name to list its members.")

    resp = await api_get(ctx, f"/v1/projects/{project_id}/users", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't list project members"))

    members = resp if isinstance(resp, list) else []
    proj_label = params.project_name or f"#{project_id}"
    if not members:
        return ActionResult.success(
            summary=f"No members found on project {proj_label}.",
            data={"project_id": project_id, "users": []},
        )

    lines = [f"• {u['username']} (ID: {u['id']})" for u in members if u.get("id")]
    return ActionResult.success(
        summary=f"{len(members)} member(s) on project {proj_label}:\n" + "\n".join(lines),
        data={"project_id": project_id, "users": members},
    )


_KANBAN_VIEW_KINDS = (4, "kanban")


async def _resolve_bucket_id_by_name(
    ctx, imperal_id: str, project_id: int, bucket_name: str
) -> int | None:
    """Resolve bucket name → bucket_id within a project's kanban view. exact → prefix → contains."""
    views_resp = await api_get(ctx, f"/v1/projects/{project_id}/views", {"imperal_id": imperal_id})
    if not isinstance(views_resp, list):
        return None
    kanban = next((v for v in views_resp if v.get("view_kind") in _KANBAN_VIEW_KINDS), None)
    if not kanban:
        return None
    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{project_id}/views/{kanban['id']}/buckets",
        {"imperal_id": imperal_id},
    )
    if not isinstance(buckets_resp, list):
        return None
    name_lower = bucket_name.strip().lower()
    for b in buckets_resp:
        if (b.get("title") or "").lower() == name_lower:
            return b["id"]
    for b in buckets_resp:
        if (b.get("title") or "").lower().startswith(name_lower):
            return b["id"]
    for b in buckets_resp:
        if name_lower in (b.get("title") or "").lower():
            return b["id"]
    return None


async def _filter_tasks_by_bucket(
    ctx, imperal_id: str, tasks: list, bucket_name: str
) -> list:
    """Narrow a list of tasks to those that live in a named bucket."""
    bn_lower = bucket_name.lower()
    project_ids = list({t.get("project_id") for t in tasks if t.get("project_id")})
    bucket_task_ids: set = set()
    for pid in project_ids:
        views_resp = await api_get(ctx, f"/v1/projects/{pid}/views", {"imperal_id": imperal_id})
        if not isinstance(views_resp, list):
            continue
        kanban = next((v for v in views_resp if v.get("view_kind") in _KANBAN_VIEW_KINDS), None)
        if not kanban:
            continue
        buckets_resp = await api_get(
            ctx, f"/v1/projects/{pid}/views/{kanban['id']}/tasks",
            {"imperal_id": imperal_id},
        )
        if not isinstance(buckets_resp, list):
            continue
        for b in buckets_resp:
            if bn_lower in (b.get("title") or "").lower():
                for t in (b.get("tasks") or []):
                    bucket_task_ids.add(t["id"])
    if bucket_task_ids:
        filtered = [t for t in tasks if t["id"] in bucket_task_ids]
        return filtered if filtered else tasks
    return tasks


async def _assign_task_impl(ctx, params: AssignTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    task_id = params.task_id
    if task_id == 0 and params.task_name:
        search_resp = await api_get(ctx, "/v1/tasks/all", {
            "imperal_id": imperal_id, "s": params.task_name, "per_page": 20,
        })
        tasks = search_resp if isinstance(search_resp, list) else []
        if not tasks:
            return ActionResult.error(
                f"Task '{params.task_name}' not found. Check the spelling or call list_my_tasks() to browse."
            )
        if len(tasks) > 1 and params.bucket_name:
            tasks = await _filter_tasks_by_bucket(ctx, imperal_id, tasks, params.bucket_name)
        if len(tasks) > 1:
            matches = ", ".join(f"#{t['id']} '{t.get('title', '?')}'" for t in tasks[:5])
            return ActionResult.error(
                f"Multiple tasks match '{params.task_name}': {matches}. "
                "Pass bucket_name to narrow down, or pass task_id directly."
            )
        task_id = tasks[0]["id"]

    if not task_id:
        return ActionResult.error(
            "task_id is required. Pass task_name to let assign_task auto-resolve by title."
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
        "Assign a person to a task. Pass task_name + assignee_query directly — "
        "do NOT call find_task or get_named_bucket_tasks first. "
        "If multiple tasks share the same name, also pass bucket_name to pick the right one. "
        "The bridge resolves assignee_query (name or email) to a Vikunja user ID automatically."
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
        "Move a task to another project. Pass integer task_id and integer project_id, "
        "or pass project_name (e.g. 'webhostmost tasks') to resolve automatically."
    ),
    data_model=UpdateTaskResult,
)
async def move_to_project(ctx, params: MoveToProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.")
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.")

    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, project_id=params.project_id))


@chat.function(
    "move_to_bucket",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.bucket_changed",
    description=(
        "Move a task to another kanban bucket (column). Pass integer task_id and integer bucket_id, "
        "or pass bucket_name + project_name (e.g. 'To-Do', 'webhostmost tasks') to resolve automatically."
    ),
    data_model=UpdateTaskResult,
)
async def move_to_bucket(ctx, params: MoveToBucketParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.bucket_id is None and params.bucket_name:
        project_id: Optional[int] = None
        if params.project_name:
            project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
            if project_id is None:
                return ActionResult.error(f"Project '{params.project_name}' not found.")
        else:
            # Fall back: get project_id from the task itself
            task_resp = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
            if isinstance(task_resp, dict) and not task_resp.get("status") == "error":
                project_id = task_resp.get("project_id")
        if project_id is None:
            return ActionResult.error(
                "Pass bucket_id directly, or pass bucket_name + project_name to resolve automatically."
            )
        params.bucket_id = await _resolve_bucket_id_by_name(ctx, imperal_id, project_id, params.bucket_name)
        if params.bucket_id is None:
            return ActionResult.error(
                f"Bucket '{params.bucket_name}' not found in project. "
                "Call list_project_buckets() to see available buckets."
            )

    if params.bucket_id is None:
        return ActionResult.error("Pass bucket_id or bucket_name + project_name.")

    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, bucket_id=params.bucket_id))


@chat.function(
    "search_vikunja_users",
    action_type="read",
    chain_callable=True,
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


@chat.function(
    "list_project_members",
    action_type="read",
    description=(
        "List the members of a specific project (its assignable users — owner plus "
        "user/team shares). Use this when the user asks who is on a named project, e.g. "
        "'who is on the WebHostMost Tasks team', 'участники проекта X', 'кто работает над проектом'. "
        "Pass project_name when you only know the name; it is resolved automatically. "
        "Prefer this over search_vikunja_users when the user names a project — it is "
        "project-scoped rather than instance-wide."
    ),
    data_model=ProjectMembersResult,
)
async def list_project_members(ctx, params: ListProjectMembersParams) -> ActionResult:
    return await _list_project_members_impl(ctx, params)
