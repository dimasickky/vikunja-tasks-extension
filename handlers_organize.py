"""tasks · Organize operations (assign, label, due, priority, move)."""

import asyncio
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, AliasChoices

from imperal_sdk.chat import ActionResult

import logging

from app import api_post, api_get, api_delete, chat, resolve_project_id
from handlers_crud import (
    _require_user,
    _update_task_impl,
    _bridge_error_msg,
    _check_batch_size,
    _resolve_task_refs,
    _BULK_CONCURRENCY,
    UpdateTaskParams,
)
from handlers_structure import _get_kanban_view_id
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD
from error_codes import TASKS_BRIDGE_ERROR, TASKS_BUCKET_NOT_FOUND, TASKS_PROJECT_NOT_FOUND, TASKS_TASK_AMBIGUOUS, TASKS_TASK_NOT_FOUND
from models_return import (
    SearchUsersResult,
    BulkTaskResult,
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
            "(e.g. 'Backlog'). Case-insensitive. Used only when task_name is set."
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
    model_config = ConfigDict(populate_by_name=True)

    task_id: int = Field(
        ...,
        description="Integer task ID. Never UUID.",
        validation_alias=AliasChoices("task_id", "id"),
    )
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't search users"), code=TASKS_BRIDGE_ERROR)

    users = resp if isinstance(resp, list) else []
    if not users:
        msg = f"No users found matching '{params.query}'." if params.query else "No other users found on this Vikunja instance."
        return ActionResult.success(summary=msg, data={"items": [], "total": 0})

    # SDL entity-list: each user is a canonical sdl.Entity (id=vikunja user id,
    # title=username, kind="user"); gateway fields kept verbatim for rendering.
    items, lines = [], []
    for u in users:
        if not isinstance(u, dict):
            continue
        it = dict(u)
        it["id"] = u.get("id") or u.get("vikunja_user_id") or 0
        it.setdefault("title", u.get("username") or u.get("name") or "")
        it.setdefault("kind", "user")
        items.append(it)
        tag = " ✓" if u.get("connected") else ""
        lines.append(f"• {it['title']} (ID: {it['id']}){tag}")

    label = f"matching '{params.query}'" if params.query else "on this Vikunja instance"
    return ActionResult.success(
        summary=f"Found {len(items)} user(s) {label}:\n" + "\n".join(lines),
        data={"items": items, "total": len(items)},
    )


async def _list_project_members_impl(ctx, params: ListProjectMembersParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    project_id = params.project_id
    if project_id is None and params.project_name:
        project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if project_id is None:
            return ActionResult.error(f"No project found matching '{params.project_name}'.", code=TASKS_PROJECT_NOT_FOUND)
    if project_id is None:
        return ActionResult.error("Pass project_id or project_name to list its members.", code=VALIDATION_MISSING_FIELD)

    resp = await api_get(ctx, f"/v1/projects/{project_id}/users", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't list project members"), code=TASKS_BRIDGE_ERROR)

    members = resp if isinstance(resp, list) else []
    proj_label = params.project_name or f"#{project_id}"
    if not members:
        return ActionResult.success(
            summary=f"No members found on project {proj_label}.",
            data={"items": [], "total": 0, "project_id": project_id},
        )

    # SDL entity-list: each member is a canonical sdl.Entity (kind="user").
    items, lines = [], []
    for u in members:
        if not isinstance(u, dict) or not u.get("id"):
            continue
        it = dict(u)
        it["id"] = u.get("id") or u.get("vikunja_user_id") or 0
        it.setdefault("title", u.get("username") or u.get("name") or "")
        it.setdefault("kind", "user")
        items.append(it)
        lines.append(f"• {it['title']} (ID: {it['id']})")

    return ActionResult.success(
        summary=f"{len(items)} member(s) on project {proj_label}:\n" + "\n".join(lines),
        data={"items": items, "total": len(items), "project_id": project_id},
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
                f"Task '{params.task_name}' not found. Check the spelling or call list_my_tasks() to browse.",
                code=TASKS_TASK_NOT_FOUND,
            )
        if len(tasks) > 1 and params.bucket_name:
            tasks = await _filter_tasks_by_bucket(ctx, imperal_id, tasks, params.bucket_name)
        if len(tasks) > 1:
            matches = ", ".join(f"#{t['id']} '{t.get('title', '?')}'" for t in tasks[:5])
            return ActionResult.error(
                f"Multiple tasks match '{params.task_name}': {matches}. "
                "Pass bucket_name to narrow down, or pass task_id directly.",
                code=TASKS_TASK_AMBIGUOUS,
            )
        task_id = tasks[0]["id"]

    if not task_id:
        return ActionResult.error(
            "task_id is required. Pass task_name to let assign_task auto-resolve by title.",
            code=VALIDATION_MISSING_FIELD,
        )

    resp = await api_post(ctx, f"/v1/tasks/{task_id}/assign",
                          {"imperal_id": imperal_id, "assignee_query": params.assignee_query})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't assign user"), code=TASKS_BRIDGE_ERROR)
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't unassign user"), code=TASKS_BRIDGE_ERROR)
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't attach label"), code=TASKS_BRIDGE_ERROR)
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't detach label"), code=TASKS_BRIDGE_ERROR)
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
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.", code=VALIDATION_MISSING_FIELD)

    return await _update_task_impl(ctx, UpdateTaskParams(task_id=params.task_id, project_id=params.project_id))


async def _move_task_to_bucket_impl(
    ctx, imperal_id: str, task_id: int, bucket_id: int,
    view_id: Optional[int] = None, task_project_id: Optional[int] = None,
    full_result: bool = True,
) -> ActionResult:
    """Move ONE task into a bucket via Vikunja's dedicated join-table endpoint.

    `bucket_id` on the regular task-update endpoint (`POST /tasks/{id}`) is a
    virtual response field, not a writable one: Vikunja echoes back whatever
    you send but never touches the underlying `task_buckets` join table
    (keyed per project_view_id) — confirmed against Vikunja's own
    kanban_task_bucket.go handler. That was already found once, for the
    bucket_id=0 detach case in create_subtask (v3.2.0 -> v3.2.1 revert), but
    never carried over to this general move path — which is why move_to_bucket
    / move_tasks_to_bucket returned success while doing nothing. The bridge's
    `.../buckets/{bucket}/tasks` route is the actual write path; this always
    goes through it instead of `_update_task_impl`.

    full_result=True (single-task callers, data_model=UpdateTaskResult) re-fetches
    the task after a successful move so the response actually carries
    title/done/due_date/priority/percent_done — matching _update_task_impl's shape.
    Batch callers pass full_result=False: they already have the title from their
    own task resolution and only care about res.status, so the extra round trip
    per task would just be N wasted requests.
    """
    project_id = task_project_id
    if project_id is None:
        task_resp = await api_get(ctx, f"/v1/tasks/{task_id}", {"imperal_id": imperal_id})
        if isinstance(task_resp, dict) and task_resp.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(task_resp, "Couldn't look up task"), code=TASKS_BRIDGE_ERROR)
        project_id = task_resp.get("project_id") if isinstance(task_resp, dict) else None
        if project_id is None:
            return ActionResult.error(f"Task #{task_id} not found.", code=TASKS_TASK_NOT_FOUND)

    if view_id is None:
        view_id, err = await _get_kanban_view_id(ctx, imperal_id, project_id)
        if err:
            return err

    resp = await api_post(
        ctx, f"/v1/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks",
        {"imperal_id": imperal_id, "task_id": task_id},
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't move task"), code=TASKS_BRIDGE_ERROR)

    if not full_result:
        return ActionResult.success(summary="moved", data={"task_id": task_id, "bucket_id": bucket_id})

    task_resp = await api_get(ctx, f"/v1/tasks/{task_id}", {"imperal_id": imperal_id})
    if isinstance(task_resp, dict) and task_resp.get("status") == "error":
        # Move itself succeeded — just couldn't confirm the read-back. Report success
        # with what we know rather than turning a completed write into an error.
        task_resp = {}

    return ActionResult.success(
        summary=f"Task moved to bucket #{bucket_id}: {task_resp.get('title', task_id)}.",
        data={
            "task_id":        task_id,
            "title":          task_resp.get("title"),
            "done":           task_resp.get("done", False),
            "due_date":       task_resp.get("due_date"),
            "priority":       task_resp.get("priority", 0),
            "percent_done":   task_resp.get("percent_done", 0.0),
            "refresh_panels": ["sidebar", "editor"],
        },
    )


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
                return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
        else:
            # Fall back: get project_id from the task itself
            task_resp = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
            if isinstance(task_resp, dict) and not task_resp.get("status") == "error":
                project_id = task_resp.get("project_id")
        if project_id is None:
            return ActionResult.error(
                "Pass bucket_id directly, or pass bucket_name + project_name to resolve automatically.",
                code=VALIDATION_MISSING_FIELD,
            )
        params.bucket_id = await _resolve_bucket_id_by_name(ctx, imperal_id, project_id, params.bucket_name)
        if params.bucket_id is None:
            return ActionResult.error(
                f"Bucket '{params.bucket_name}' not found in project. "
                "Call list_project_buckets() to see available buckets.",
                code=TASKS_BUCKET_NOT_FOUND,
            )

    if params.bucket_id is None:
        return ActionResult.error("Pass bucket_id or bucket_name + project_name.", code=VALIDATION_MISSING_FIELD)

    return await _move_task_to_bucket_impl(ctx, imperal_id, params.task_id, params.bucket_id)


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


class MoveTasksToBucketParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_ids: Optional[List[int]] = Field(
        None,
        description="List of integer task IDs to move. Use this if you already have the IDs.",
        validation_alias=AliasChoices("task_ids", "ids"),
    )
    task_titles: Optional[List[str]] = Field(
        None,
        description="List of task titles to find and move (e.g. ['Buy milk', 'Fix login']). Auto-resolved to IDs.",
    )
    bucket_id: Optional[int] = Field(
        None,
        description="Target kanban bucket ID. Pass bucket_name + project_name instead if unknown.",
    )
    bucket_name: Optional[str] = Field(
        None,
        description="Target bucket name (e.g. 'Done', 'In Progress'). Requires project_name to resolve.",
    )
    project_id: Optional[int] = Field(
        None,
        description="Project the bucket belongs to, and the scope for title lookups.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Project name (e.g. 'WebHostMost Tasks') — resolves both the bucket and the title search scope.",
    )


@chat.function(
    "move_tasks_to_bucket",
    action_type="write",
    chain_callable=True,
    effects=["update:task"],
    event="tasks.bucket_changed",
    description=(
        "Move MULTIPLE tasks to the same kanban bucket (column) at once. Pass task_ids (list of "
        "integers) OR task_titles (list of names), plus bucket_id OR bucket_name + project_name. "
        "Use when the user asks to move 2+ tasks to a column in one request."
    ),
    data_model=BulkTaskResult,
)
async def move_tasks_to_bucket(ctx, params: MoveTasksToBucketParams) -> ActionResult:
    """Move a set of tasks into one bucket, reported per task.

    The board-level case: "push all of these to Done". Note the bucket is
    resolved ONCE for the whole batch rather than per task — the single-task
    tool has to resolve it every call, and repeating that N times would add N
    lookups for an answer that cannot change between them.

    Non-destructive: a move is trivially reversible by moving back, so this
    goes straight through without a preview gate, unlike delete_projects.
    """
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if not params.task_ids and not params.task_titles:
        return ActionResult.error("Pass task_ids or task_titles.", code=VALIDATION_MISSING_FIELD)

    oversized = _check_batch_size(
        (params.task_ids or []) + (params.task_titles or []), "tasks")
    if oversized:
        return oversized

    project_id = params.project_id
    if project_id is None and params.project_name:
        project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if project_id is None:
            return ActionResult.error(
                f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)

    bucket_id = params.bucket_id
    if bucket_id is None and params.bucket_name:
        if project_id is None:
            return ActionResult.error(
                "Pass bucket_id directly, or bucket_name + project_name to resolve it.",
                code=VALIDATION_MISSING_FIELD,
            )
        bucket_id = await _resolve_bucket_id_by_name(ctx, imperal_id, project_id, params.bucket_name)
        if bucket_id is None:
            return ActionResult.error(
                f"Bucket '{params.bucket_name}' not found in project. "
                "Call list_project_buckets() to see available buckets.",
                code=TASKS_BUCKET_NOT_FOUND,
            )

    if bucket_id is None:
        return ActionResult.error(
            "Pass bucket_id or bucket_name + project_name.", code=VALIDATION_MISSING_FIELD)

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)
    refs = await _resolve_task_refs(
        ctx, imperal_id, sem, params.task_ids, params.task_titles, project_id)

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, project_id) if project_id is not None else (None, None)
    if project_id is not None and err:
        return err

    async def _move_one(task_id: int, title: str) -> dict:
        if task_id == -1:
            return {"task_id": -1, "title": title, "ok": False, "error": "task not found"}
        async with sem:
            res = await _move_task_to_bucket_impl(
                ctx, imperal_id, task_id, bucket_id, view_id=view_id,
                task_project_id=project_id, full_result=False)
        if res.status == "error":
            return {"task_id": task_id, "title": title, "ok": False,
                    "error": res.summary or "move failed"}
        return {"task_id": task_id, "title": title, "ok": True}

    results = list(await asyncio.gather(*(_move_one(tid, t) for tid, t in refs)))

    succeeded = sum(1 for r in results if r["ok"])
    failed = len(results) - succeeded

    if failed == 0:
        summary = f"Moved {succeeded} task(s)."
    else:
        broken = ", ".join(f"{r['title']} ({r['error']})" for r in results if not r["ok"])
        summary = f"Moved {succeeded} of {len(results)} task(s) — {failed} failed: {broken}"

    return ActionResult.success(
        summary=summary,
        data={
            "succeeded_count": succeeded,
            "failed_count": failed,
            "results": results,
            "refresh_panels": ["sidebar", "editor"],
        },
    )
