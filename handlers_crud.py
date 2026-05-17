"""tasks · CRUD lifecycle functions (create / update / complete / delete)."""

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, chat, imperal_id_of, is_no_connection_error
from panels_task import _toggle_checklist_item
from models_return import (
    CreateTaskResult,
    UpdateTaskResult,
    TaskStatusResult,
    DeleteTaskResult,
    CreateSubtaskResult,
    ListSubtasksResult,
    ToggleChecklistResult,
    GetTaskResult,
)


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
        return ActionResult.error("No authenticated user on context.")
    return imperal_id


def _bridge_error_msg(resp: dict, default_prefix: str) -> str:
    if is_no_connection_error(resp):
        return "No Vikunja connected. Connect your Vikunja in the tasks panel first."
    detail = resp.get("detail")
    if isinstance(detail, dict):
        detail = detail.get("detail") or detail.get("error") or detail.get("message") or str(detail)
    return f"{default_prefix}: {detail}"


async def _create_task_impl(ctx, params: CreateTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create task"))

    return ActionResult.success(
        summary=f"Task created: {resp['title']} (project #{resp['project_id']}).",
        data={
            "task_id":    resp["id"],
            "title":      resp["title"],
            "project_id": resp["project_id"],
            "due_date":   resp.get("due_date"),
            "priority":   resp.get("priority", 0),
            "bucket_id":  resp.get("bucket_id", 0),
            "refresh_panels": ["sidebar", "editor"],
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
        return ActionResult.error("No fields to update — pass at least one field.")

    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update task"))

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't complete task"))

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't reopen task"))

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete task"))

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
    description="Create a new task in a project. Returns task_id + full task details.",
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create subtask"))

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch subtasks"))

    subtasks = resp if isinstance(resp, list) else []
    done_ct = sum(1 for s in subtasks if s.get("done"))
    return ActionResult.success(
        summary=f"Task #{params.task_id} has {len(subtasks)} subtask(s), {done_ct} done.",
        data={
            "task_id":  params.task_id,
            "subtasks": [
                {"task_id": s["id"], "title": s["title"], "done": s.get("done", False)}
                for s in subtasks
            ],
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
        return ActionResult.error(_bridge_error_msg(task, "Couldn't fetch task"))

    desc = task.get("description") or ""
    new_desc = _toggle_checklist_item(desc, params.item_index, params.checked)
    if new_desc == desc:
        return ActionResult.error(
            f"Checklist item #{params.item_index} not found in task description."
        )

    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}", {
        "imperal_id": imperal_id,
        "description": new_desc,
    })
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update checklist item"))

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
    data_model=GetTaskResult,
)
async def get_task(ctx, params: GetTaskParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, f"/v1/tasks/{params.task_id}", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch task"))

    t = resp
    assignees = [
        {"vikunja_user_id": a.get("id"), "username": a.get("username", "")}
        for a in (t.get("assignees") or [])
    ]
    labels = [
        {"label_id": l.get("id"), "title": l.get("title", ""), "hex_color": l.get("hex_color")}
        for l in (t.get("labels") or [])
    ]
    return ActionResult.success(
        summary=f"Task #{params.task_id}: {t.get('title', '?')} ({'done' if t.get('done') else 'open'})",
        data={
            "task_id":      t.get("id"),
            "title":        t.get("title", ""),
            "description":  t.get("description", ""),
            "done":         t.get("done", False),
            "due_date":     (t.get("due_date") or "")[:10] or None,
            "start_date":   (t.get("start_date") or "")[:10] or None,
            "priority":     t.get("priority", 0),
            "percent_done": t.get("percent_done", 0.0),
            "project_id":   t.get("project_id"),
            "bucket_id":    t.get("bucket_id") or None,
            "hex_color":    t.get("hex_color"),
            "is_favorite":  t.get("is_favorite", False),
            "assignees":    assignees,
            "labels":       labels,
            "created":      t.get("created"),
            "updated":      t.get("updated"),
        },
    )
