"""tasks · Structure operations — projects and labels CRUD."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, chat
from handlers_crud import _require_user


# ─── Params ────────────────────────────────────────────────────────────── #

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
    label_id: int


# ─── Impl ──────────────────────────────────────────────────────────────── #

async def _create_project_impl(ctx, params: CreateProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {
        "imperal_id": imperal_id,
        "title": params.title,
        "description": params.description,
    }
    if params.parent_project_id is not None:
        payload["parent_project_id"] = params.parent_project_id
    if params.hex_color is not None:
        payload["hex_color"] = params.hex_color

    resp = await api_post("/v1/projects", payload)
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось создать проект: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Создал проект «{resp['title']}».",
        data={
            "project_id": resp["id"],
            "title": resp["title"],
            "hex_color": resp.get("hex_color"),
            "parent_project_id": resp.get("parent_project_id", 0),
        },
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
        return ActionResult.error("Нет полей для обновления.")

    resp = await api_post(f"/v1/projects/{params.project_id}", payload)
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось обновить проект: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Обновил проект «{resp.get('title', params.project_id)}».",
        data={"project_id": resp.get("id", params.project_id), "title": resp.get("title")},
    )


async def _archive_project_impl(ctx, params: ArchiveProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        f"/v1/projects/{params.project_id}",
        {"imperal_id": imperal_id, "is_archived": True},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось архивировать проект: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Архивировал проект #{params.project_id}.",
        data={"project_id": params.project_id, "is_archived": True},
    )


async def _delete_project_impl(ctx, params: DeleteProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        f"/v1/projects/{params.project_id}",
        params={"imperal_id": imperal_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось удалить проект: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Удалил проект #{params.project_id} (с каскадом).",
        data={"project_id": params.project_id, "deleted": True},
    )


async def _create_label_impl(ctx, params: CreateLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    payload = {"imperal_id": imperal_id, "title": params.title, "description": params.description}
    if params.hex_color is not None:
        payload["hex_color"] = params.hex_color

    resp = await api_post("/v1/labels", payload)
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось создать метку: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Создал метку «{resp['title']}».",
        data={"label_id": resp["id"], "title": resp["title"], "hex_color": resp.get("hex_color")},
    )


async def _delete_label_impl(ctx, params: DeleteLabelParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        f"/v1/labels/{params.label_id}",
        params={"imperal_id": imperal_id},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось удалить метку: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Удалил метку #{params.label_id}.",
        data={"label_id": params.label_id, "deleted": True},
    )


# ─── @chat.function wrappers ───────────────────────────────────────────── #

@chat.function(
    "create_project",
    action_type="write",
    event="project.created",
    description="Create a new project (kanban board). Returns project_id.",
)
async def create_project(ctx, params: CreateProjectParams) -> ActionResult:
    return await _create_project_impl(ctx, params)


@chat.function(
    "update_project",
    action_type="write",
    event="project.updated",
    description="Update project title, description, or color.",
)
async def update_project(ctx, params: UpdateProjectParams) -> ActionResult:
    return await _update_project_impl(ctx, params)


@chat.function(
    "archive_project",
    action_type="write",
    event="project.archived",
    description="Archive a project (is_archived=true) — hide from active views but keep data.",
)
async def archive_project(ctx, params: ArchiveProjectParams) -> ActionResult:
    return await _archive_project_impl(ctx, params)


@chat.function(
    "delete_project",
    action_type="destructive",
    event="project.deleted",
    description="Permanently delete a project with all its tasks. Cannot be undone.",
)
async def delete_project(ctx, params: DeleteProjectParams) -> ActionResult:
    return await _delete_project_impl(ctx, params)


@chat.function(
    "create_label",
    action_type="write",
    event="label.created",
    description="Create a new label with title and optional color.",
)
async def create_label(ctx, params: CreateLabelParams) -> ActionResult:
    return await _create_label_impl(ctx, params)


@chat.function(
    "delete_label",
    action_type="destructive",
    event="label.deleted",
    description="Permanently delete a label — removes from all tasks.",
)
async def delete_label(ctx, params: DeleteLabelParams) -> ActionResult:
    return await _delete_label_impl(ctx, params)
