"""tasks · Structure operations — projects, labels, and kanban buckets."""

import logging
from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, chat, NoParams
from handlers_crud import _require_user, _bridge_error_msg
from models_return import (
    CreateProjectResult,
    UpdateProjectResult,
    ArchiveProjectResult,
    DeleteProjectResult,
    LabelItem,
    ListLabelsResult,
    CreateLabelResult,
    DeleteLabelResult,
    ListProjectsResult,
    ListBucketsResult,
)

log = logging.getLogger("tasks")

# Vikunja returns view_kind as string in older versions, integer in v0.21+.
# 4 (int) == "kanban" (str) — support both to be version-agnostic.
_KANBAN_VIEW_KINDS = {"kanban", 4}


class CreateProjectParams(BaseModel):
    title: str = Field(..., min_length=1, max_length=250)
    description: str = ""
    parent_project_id: Optional[int] = None
    hex_color: Optional[str] = Field(None, description="e.g. 'ff5500' — without '#'.")


class UpdateProjectParams(BaseModel):
    project_id: int
    title: Optional[str] = None
    description: Optional[str] = None
    hex_color: Optional[str] = None


class ArchiveProjectParams(BaseModel):
    project_id: int


class DeleteProjectParams(BaseModel):
    project_id: int


class CreateLabelParams(BaseModel):
    title: str = Field(..., min_length=1, max_length=250)
    description: str = ""
    hex_color: Optional[str] = None


class DeleteLabelParams(BaseModel):
    label_id: int = Field(..., description="Integer label ID from list_labels response. Never a name.")


class ListBucketsParams(BaseModel):
    project_id: int = Field(
        ...,
        description=(
            "Integer project ID. REQUIRED — call list_projects() first if you only "
            "know the project name."
        ),
    )


# ─── Impl ─────────────────────────────────────────────────────────────────── #

async def _create_project_impl(ctx, params: CreateProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {"imperal_id": imperal_id, "title": params.title, "description": params.description}
    if params.parent_project_id is not None: payload["parent_project_id"] = params.parent_project_id
    if params.hex_color is not None:         payload["hex_color"] = params.hex_color

    resp = await api_post(ctx, "/v1/projects", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create project"))

    return ActionResult.success(
        summary=f"Project created: {resp['title']}.",
        data={"project_id": resp["id"], "title": resp["title"],
              "hex_color": resp.get("hex_color"),
              "parent_project_id": resp.get("parent_project_id", 0),
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _update_project_impl(ctx, params: UpdateProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {"imperal_id": imperal_id}
    for field in ("title", "description", "hex_color"):
        v = getattr(params, field)
        if v is not None:
            payload[field] = v

    if len(payload) == 1:
        return ActionResult.error("No fields to update.")

    resp = await api_post(ctx, f"/v1/projects/{params.project_id}", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update project"))

    return ActionResult.success(
        summary=f"Project updated: {resp.get('title', params.project_id)}.",
        data={"project_id": resp.get("id", params.project_id), "title": resp.get("title"),
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _archive_project_impl(ctx, params: ArchiveProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(ctx, f"/v1/projects/{params.project_id}",
                          {"imperal_id": imperal_id, "is_archived": True})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't archive project"))

    return ActionResult.success(
        summary=f"Project #{params.project_id} archived.",
        data={"project_id": params.project_id, "is_archived": True,
              "refresh_panels": ["sidebar", "editor"]},
    )


async def _delete_project_impl(ctx, params: DeleteProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(ctx, f"/v1/projects/{params.project_id}", params={"imperal_id": imperal_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete project"))

    return ActionResult.success(
        summary=f"Project #{params.project_id} deleted (cascade).",
        data={"project_id": params.project_id, "deleted": True, "refresh_panels": ["sidebar", "editor"]},
    )


async def _list_labels_impl(ctx) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, "/v1/labels", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch labels"))

    labels = resp if isinstance(resp, list) else []
    return ActionResult.success(
        summary=f"{len(labels)} label(s): {', '.join(l.get('title', '?') for l in labels[:10])}.",
        data={
            "count": len(labels),
            "labels": [
                {
                    "label_id":  l["id"],
                    "title":     l.get("title", "?"),
                    "hex_color": l.get("hex_color"),
                }
                for l in labels
            ],
        },
    )


async def _create_label_impl(ctx, params: CreateLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {"imperal_id": imperal_id, "title": params.title, "description": params.description}
    if params.hex_color is not None:
        payload["hex_color"] = params.hex_color

    resp = await api_post(ctx, "/v1/labels", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create label"))

    return ActionResult.success(
        summary=f"Label created: {resp['title']}.",
        data={"label_id": resp["id"], "title": resp["title"],
              "hex_color": resp.get("hex_color"), "refresh_panels": ["sidebar", "editor"]},
    )


async def _delete_label_impl(ctx, params: DeleteLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(ctx, f"/v1/labels/{params.label_id}", params={"imperal_id": imperal_id})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete label"))

    return ActionResult.success(
        summary=f"Label #{params.label_id} deleted.",
        data={"label_id": params.label_id, "deleted": True, "refresh_panels": ["sidebar", "editor"]},
    )


async def _list_projects_impl(ctx) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, "/v1/projects", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch projects"))

    projects = resp if isinstance(resp, list) else []
    active = [p for p in projects if not p.get("is_archived", False)]
    return ActionResult.success(
        summary=f"{len(active)} project(s): {', '.join(p.get('title', '?') for p in active[:10])}.",
        data={
            "count":    len(active),
            "projects": [
                {"project_id": p["id"], "title": p.get("title", "?"), "hex_color": p.get("hex_color")}
                for p in active
            ],
        },
    )


# ─── @chat.function wrappers ──────────────────────────────────────────────── #

@chat.function(
    "create_project",
    action_type="write",
    chain_callable=True,
    effects=["create:project"],
    event="project.created",
    description="Create a new project (kanban board). Returns project_id.",
    data_model=CreateProjectResult,
)
async def create_project(ctx, params: CreateProjectParams) -> ActionResult:
    return await _create_project_impl(ctx, params)


@chat.function(
    "update_project",
    action_type="write",
    chain_callable=True,
    effects=["update:project"],
    event="project.updated",
    description="Update project title, description, or color.",
    data_model=UpdateProjectResult,
)
async def update_project(ctx, params: UpdateProjectParams) -> ActionResult:
    return await _update_project_impl(ctx, params)


@chat.function(
    "archive_project",
    action_type="write",
    chain_callable=True,
    effects=["update:project"],
    event="project.archived",
    description="Archive a project (is_archived=true) — hide from active views but keep data.",
    data_model=ArchiveProjectResult,
)
async def archive_project(ctx, params: ArchiveProjectParams) -> ActionResult:
    return await _archive_project_impl(ctx, params)


@chat.function(
    "delete_project",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:project"],
    event="project.deleted",
    description="Permanently delete a project with all its tasks. Cannot be undone.",
    data_model=DeleteProjectResult,
)
async def delete_project(ctx, params: DeleteProjectParams) -> ActionResult:
    return await _delete_project_impl(ctx, params)


@chat.function(
    "list_labels",
    action_type="read",
    description=(
        "List all labels on this Vikunja instance. Returns label_id and title. "
        "Call this first when the user refers to a label by name — "
        "then use the returned label_id in add_label."
    ),
    data_model=ListLabelsResult,
)
async def list_labels(ctx, params: NoParams) -> ActionResult:
    return await _list_labels_impl(ctx)


@chat.function(
    "create_label",
    action_type="write",
    chain_callable=True,
    effects=["create:label"],
    event="label.created",
    description="Create a new label with title and optional hex color. Returns label_id.",
    data_model=CreateLabelResult,
)
async def create_label(ctx, params: CreateLabelParams) -> ActionResult:
    return await _create_label_impl(ctx, params)


@chat.function(
    "delete_label",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:label"],
    event="label.deleted",
    description="Permanently delete a label — removes it from all tasks.",
    data_model=DeleteLabelResult,
)
async def delete_label(ctx, params: DeleteLabelParams) -> ActionResult:
    return await _delete_label_impl(ctx, params)


@chat.function(
    "list_projects",
    action_type="read",
    description=(
        "List all active (non-archived) projects. Returns project_id and title. "
        "ALWAYS call this first when the user refers to a project by name — "
        "then use the returned project_id in list_buckets, filter_tasks, or create_task."
    ),
    data_model=ListProjectsResult,
)
async def list_projects(ctx, params: NoParams) -> ActionResult:
    return await _list_projects_impl(ctx)


@chat.function(
    "list_buckets",
    action_type="read",
    description=(
        "List kanban buckets (columns) for a project WITH their tasks embedded. "
        "REQUIRES project_id — call list_projects() first if you only know the project name. "
        "Returns bucket_id, title, task_count, and full task list per bucket. "
        "Use for: (1) get tasks from a named bucket — read from the tasks array directly; "
        "(2) resolve bucket name → bucket_id before move_to_bucket or create_task; "
        "(3) count total tasks in a project (sum all task_count values). "
        "NOTE: filter_tasks cannot filter by bucket — this is the only way to get bucket tasks."
    ),
    data_model=ListBucketsResult,
)
async def list_buckets(ctx, params: ListBucketsParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    views_resp = await api_get(ctx, f"/v1/projects/{params.project_id}/views",
                               {"imperal_id": imperal_id})
    if isinstance(views_resp, dict) and views_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(views_resp, "Couldn't fetch project views"))

    views = views_resp if isinstance(views_resp, list) else []
    kanban = next((v for v in views if v.get("view_kind") in _KANBAN_VIEW_KINDS), None)
    if kanban is None:
        view_names = [str(v.get("view_kind", "?")) for v in views]
        return ActionResult.error(
            f"Project #{params.project_id} has no kanban (board) view. "
            f"Available view types: {', '.join(view_names) or 'none'}. "
            "Open Vikunja and add a Board view to this project, then try again."
        )

    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{params.project_id}/views/{kanban['id']}/tasks",
        {"imperal_id": imperal_id},
    )
    if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(buckets_resp, "Couldn't fetch buckets"))

    buckets = buckets_resp if isinstance(buckets_resp, list) else []

    def _task_entry(t: dict) -> dict:
        due = (t.get("due_date") or "")[:10]
        return {
            "task_id":  t["id"],
            "title":    t.get("title", "?"),
            "done":     t.get("done", False),
            "priority": t.get("priority", 0),
            "due_date": due or None,
        }

    bucket_list = [
        {
            "bucket_id":   b["id"],
            "title":       b.get("title", "?"),
            "limit":       b.get("limit", 0),
            "task_count":  len(b.get("tasks") or []),
            "tasks":       [_task_entry(t) for t in (b.get("tasks") or [])],
        }
        for b in buckets
    ]
    summary_parts = [f"{b['title']} ({b['task_count']})" for b in bucket_list]
    return ActionResult.success(
        summary=f"{len(buckets)} bucket(s): {', '.join(summary_parts)}.",
        data={"project_id": params.project_id, "buckets": bucket_list},
    )
