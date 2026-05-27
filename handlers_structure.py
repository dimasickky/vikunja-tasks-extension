"""tasks · Structure operations — projects, labels, and kanban buckets."""

import logging
from typing import Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, chat, NoParams, resolve_project_id
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
    BucketNavItem,
    ListProjectBucketsResult,
    GetBucketTasksResult,
    RenameBucketResult,
    CreateBucketResult,
    DeleteBucketResult,
    ListProjectTasksResult,
    GetProjectResult,
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
    project_id: Optional[int] = Field(
        None,
        description=(
            "Integer project ID. Pass project_name instead if unknown."
        ),
    )
    project_name: Optional[str] = Field(
        None,
        description=(
            "Project name to look up (e.g. 'webhostmost tasks'). Used when project_id is unknown."
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
        "Pass project_id OR project_name (e.g. 'webhostmost tasks') — name is resolved automatically. "
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

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.")
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.")

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


# ─── Tier-2: focused bucket endpoints ─────────────────────────────────────── #

class ListProjectBucketsParams(BaseModel):
    project_id: Optional[int] = Field(
        None,
        description="Integer project ID. Pass project_name instead if unknown.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Project name to look up (e.g. 'webhostmost tasks'). Used when project_id is unknown.",
    )


class GetBucketTasksParams(BaseModel):
    project_id: int = Field(..., description="Integer project ID.")
    bucket_id: int = Field(..., description="Integer bucket ID from list_project_buckets.")


class GetNamedBucketTasksParams(BaseModel):
    project_name: str = Field(
        ...,
        description="Project name as the user said it (e.g. 'WebHostMost Tasks'). Case-insensitive, prefix match.",
    )
    bucket_name: str = Field(
        ...,
        description="Bucket/column name as the user said it (e.g. 'the team'). Case-insensitive, prefix match.",
    )


async def _get_kanban_view_id(ctx, imperal_id: str, project_id: int) -> tuple[int | None, ActionResult | None]:
    """Return (view_id, None) or (None, error ActionResult)."""
    views_resp = await api_get(ctx, f"/v1/projects/{project_id}/views", {"imperal_id": imperal_id})
    if isinstance(views_resp, dict) and views_resp.get("status") == "error":
        return None, ActionResult.error(_bridge_error_msg(views_resp, "Couldn't fetch project views"))
    views = views_resp if isinstance(views_resp, list) else []
    kanban = next((v for v in views if v.get("view_kind") in _KANBAN_VIEW_KINDS), None)
    if kanban is None:
        kinds = [str(v.get("view_kind", "?")) for v in views]
        return None, ActionResult.error(
            f"Project #{project_id} has no kanban (board) view. "
            f"Available view types: {', '.join(kinds) or 'none'}. "
            "Open Vikunja and add a Board view to this project first."
        )
    return kanban["id"], None


def _match_by_name(items: list[dict], name: str, title_key: str = "title") -> dict | None:
    """Case-insensitive: exact → prefix → contains."""
    target = name.strip().lower()
    exact   = next((i for i in items if i.get(title_key, "").strip().lower() == target), None)
    if exact:   return exact
    prefix  = next((i for i in items if i.get(title_key, "").strip().lower().startswith(target)), None)
    if prefix:  return prefix
    return next((i for i in items if target in i.get(title_key, "").strip().lower()), None)


@chat.function(
    "list_project_buckets",
    action_type="read",
    description=(
        "List kanban columns (buckets) for a project — names and IDs only, NO task data. "
        "Pass project_id OR project_name (e.g. 'webhostmost tasks') — name is resolved automatically. "
        "Use this to resolve a bucket name → bucket_id before calling get_bucket_tasks, "
        "move_to_bucket, or create_task with a specific bucket."
    ),
    data_model=ListProjectBucketsResult,
)
async def list_project_buckets(ctx, params: ListProjectBucketsParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.")
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.")

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/buckets",
        {"imperal_id": imperal_id},
    )
    if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(buckets_resp, "Couldn't fetch buckets"))

    buckets = buckets_resp if isinstance(buckets_resp, list) else []

    # Fetch project title for context
    proj_resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    proj_title = proj_resp.get("title", f"#{params.project_id}") if isinstance(proj_resp, dict) else f"#{params.project_id}"

    bucket_list = [
        {
            "bucket_id":      b["id"],
            "title":          b.get("title", "?"),
            "limit":          b.get("limit", 0),
            "is_done_bucket": b.get("is_done_bucket", False),
        }
        for b in buckets
    ]
    names = ", ".join(b["title"] for b in bucket_list)
    return ActionResult.success(
        summary=f"Project '{proj_title}' has {len(bucket_list)} bucket(s): {names}.",
        data={
            "project_id":    params.project_id,
            "project_title": proj_title,
            "bucket_count":  len(bucket_list),
            "buckets":       bucket_list,
        },
    )


@chat.function(
    "get_bucket_tasks",
    action_type="read",
    description=(
        "Get tasks from a specific bucket (column) by integer bucket_id. "
        "Returns ONLY tasks from that bucket — nothing else. "
        "Use list_project_buckets() first to resolve a bucket name to bucket_id. "
        "Prefer get_named_bucket_tasks() when you only know the name."
    ),
    data_model=GetBucketTasksResult,
)
async def get_bucket_tasks(ctx, params: GetBucketTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/tasks",
        {"imperal_id": imperal_id},
    )
    if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(buckets_resp, "Couldn't fetch bucket tasks"))

    buckets = buckets_resp if isinstance(buckets_resp, list) else []
    target = next((b for b in buckets if b.get("id") == params.bucket_id), None)
    if target is None:
        available = [f"#{b['id']} '{b.get('title','?')}'" for b in buckets]
        return ActionResult.error(
            f"Bucket #{params.bucket_id} not found in project #{params.project_id}. "
            f"Available: {', '.join(available) or 'none'}."
        )

    def _task_entry(t: dict) -> dict:
        due = (t.get("due_date") or "")[:10]
        return {
            "task_id":  t["id"],
            "title":    t.get("title", "?"),
            "done":     t.get("done", False),
            "priority": t.get("priority", 0),
            "due_date": due or None,
        }

    task_list = [_task_entry(t) for t in (target.get("tasks") or [])]
    return ActionResult.success(
        summary=f"Bucket '{target.get('title','?')}': {len(task_list)} task(s).",
        data={
            "project_id":    params.project_id,
            "bucket_id":     params.bucket_id,
            "bucket_title":  target.get("title", "?"),
            "task_count":    len(task_list),
            "tasks":         task_list,
        },
    )


@chat.function(
    "get_named_bucket_tasks",
    action_type="read",
    description=(
        "Get tasks from a bucket by project name + bucket name. "
        "Resolves names to IDs automatically and returns ONLY those tasks. "
        "USE THIS as the primary way to get tasks from a named bucket — "
        "one call does everything: project lookup, bucket lookup, task retrieval. "
        "Names are case-insensitive and support prefix matching."
    ),
    data_model=GetBucketTasksResult,
)
async def get_named_bucket_tasks(ctx, params: GetNamedBucketTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    # Step 1: resolve project name → project_id
    projects_resp = await api_get(ctx, "/v1/projects", {"imperal_id": imperal_id})
    if isinstance(projects_resp, dict) and projects_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(projects_resp, "Couldn't fetch projects"))

    projects = [p for p in (projects_resp if isinstance(projects_resp, list) else [])
                if not p.get("is_archived", False)]
    project = _match_by_name(projects, params.project_name, title_key="title")
    if project is None:
        available = [p.get("title", "?") for p in projects[:10]]
        return ActionResult.error(
            f"Project '{params.project_name}' not found. "
            f"Available projects: {', '.join(available) or 'none'}. "
            "Check the spelling or call list_projects() to see all projects."
        )
    project_id = project["id"]
    project_title = project.get("title", f"#{project_id}")

    # Step 2: find kanban view
    view_id, err = await _get_kanban_view_id(ctx, imperal_id, project_id)
    if err:
        return err

    # Step 3: get buckets WITH tasks in one call, filter to target bucket
    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{project_id}/views/{view_id}/tasks",
        {"imperal_id": imperal_id},
    )
    if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(buckets_resp, "Couldn't fetch bucket tasks"))

    buckets = buckets_resp if isinstance(buckets_resp, list) else []
    bucket = _match_by_name(buckets, params.bucket_name, title_key="title")
    if bucket is None:
        available = [b.get("title", "?") for b in buckets]
        return ActionResult.error(
            f"Bucket '{params.bucket_name}' not found in project '{project_title}'. "
            f"Available buckets: {', '.join(available) or 'none'}."
        )

    def _task_entry(t: dict) -> dict:
        due = (t.get("due_date") or "")[:10]
        return {
            "task_id":  t["id"],
            "title":    t.get("title", "?"),
            "done":     t.get("done", False),
            "priority": t.get("priority", 0),
            "due_date": due or None,
        }

    task_list = [_task_entry(t) for t in (bucket.get("tasks") or [])]
    return ActionResult.success(
        summary=(
            f"Bucket '{bucket.get('title','?')}' in '{project_title}': "
            f"{len(task_list)} task(s)."
        ),
        data={
            "project_id":   project_id,
            "bucket_id":    bucket["id"],
            "bucket_title": bucket.get("title", "?"),
            "task_count":   len(task_list),
            "tasks":        task_list,
        },
    )


class CreateBucketParams(BaseModel):
    project_id: int = Field(..., description="Integer project ID from list_projects.")
    title: str = Field(..., min_length=1, max_length=250, description="Column name.")
    limit: Optional[int] = Field(None, ge=0, description="WIP limit (0 = no limit). Omit for unlimited.")


class DeleteBucketParams(BaseModel):
    project_id: int = Field(..., description="Integer project ID.")
    bucket_id: int = Field(..., description="Integer bucket ID from list_project_buckets.")


class RenameBucketParams(BaseModel):
    project_id: int = Field(..., description="Integer project ID.")
    bucket_id: int = Field(..., description="Integer bucket ID from list_project_buckets.")
    title: str = Field(..., min_length=1, max_length=250, description="New bucket name.")
    limit: Optional[int] = Field(None, ge=0, description="WIP limit (0 = no limit). Omit to keep existing.")


@chat.function(
    "rename_bucket",
    action_type="write",
    chain_callable=True,
    effects=["update:bucket"],
    event="task.bucket_changed",
    description=(
        "Rename a kanban bucket (column) or update its WIP limit. "
        "Requires project_id and bucket_id — use list_project_buckets() first "
        "if you only know the bucket name."
    ),
    data_model=RenameBucketResult,
)
async def rename_bucket(ctx, params: RenameBucketParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    payload: dict = {"imperal_id": imperal_id, "title": params.title}
    if params.limit is not None:
        payload["limit"] = params.limit

    resp = await api_post(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/buckets/{params.bucket_id}",
        payload,
    )
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't rename bucket"))

    return ActionResult.success(
        summary=f"Bucket renamed to '{params.title}'.",
        data={
            "project_id":     params.project_id,
            "bucket_id":      params.bucket_id,
            "title":          resp.get("title", params.title),
            "limit":          resp.get("limit", 0),
            "refresh_panels": ["editor"],
        },
    )


@chat.function(
    "create_bucket",
    action_type="write",
    chain_callable=True,
    effects=["create:bucket"],
    event="task.bucket_changed",
    description=(
        "Create a new kanban column (bucket) in a project. "
        "Requires project_id — use list_projects() first if you only know the project name. "
        "Optional WIP limit: 0 means no limit."
    ),
    data_model=CreateBucketResult,
)
async def create_bucket(ctx, params: CreateBucketParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    payload: dict = {"imperal_id": imperal_id, "title": params.title}
    if params.limit is not None:
        payload["limit"] = params.limit

    resp = await api_post(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/buckets",
        payload,
    )
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create bucket"))

    return ActionResult.success(
        summary=f"Created bucket '{params.title}' in project #{params.project_id}.",
        data={
            "project_id":     params.project_id,
            "bucket_id":      resp.get("id"),
            "title":          resp.get("title", params.title),
            "limit":          resp.get("limit", 0),
            "refresh_panels": ["editor"],
        },
    )


@chat.function(
    "delete_bucket",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:bucket"],
    event="task.bucket_changed",
    description=(
        "Delete a kanban column (bucket) from a project. Irreversible — "
        "tasks in the deleted column are moved to the project's default column, not deleted. "
        "Requires project_id and bucket_id — call list_project_buckets() first if you only know the name."
    ),
    data_model=DeleteBucketResult,
)
async def delete_bucket(ctx, params: DeleteBucketParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    resp = await api_delete(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/buckets/{params.bucket_id}",
        {"imperal_id": imperal_id},
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete bucket"))

    return ActionResult.success(
        summary=f"Deleted bucket #{params.bucket_id} from project #{params.project_id}.",
        data={
            "project_id":     params.project_id,
            "bucket_id":      params.bucket_id,
            "deleted":        True,
            "refresh_panels": ["editor"],
        },
    )


# ─── list_project_tasks ────────────────────────────────────────────────────── #

class ListProjectTasksParams(BaseModel):
    project_id: Optional[int] = Field(None, description="Integer project ID.")
    project_name: Optional[str] = Field(
        None,
        description=(
            "Project name (e.g. 'webhostmost tasks'). Used when project_id unknown."
        ),
    )
    filter: Optional[str] = Field(None, description="Additional Vikunja filter expression.")
    page: int = Field(1, ge=1)
    per_page: int = Field(50, ge=1, le=200)


@chat.function(
    "list_project_tasks",
    action_type="read",
    description=(
        "List all tasks in a specific project. Pass project_name (e.g. 'WebHostMost Tasks') "
        "or project_id. Use when the user asks to see tasks in a named project. "
        "Returns task list with title, done status, priority, and due date per task."
    ),
    data_model=ListProjectTasksResult,
)
async def list_project_tasks(ctx, params: ListProjectTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.")
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.")

    query_params: dict = {"imperal_id": imperal_id, "page": params.page, "per_page": params.per_page}
    if params.filter:
        query_params["filter"] = params.filter

    # Fetch project title for summary
    proj_resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    proj_title = proj_resp.get("title", f"#{params.project_id}") if isinstance(proj_resp, dict) else f"#{params.project_id}"

    tasks_resp = await api_get(ctx, f"/v1/projects/{params.project_id}/tasks", query_params)
    if isinstance(tasks_resp, dict) and tasks_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(tasks_resp, "Couldn't fetch project tasks"))

    tasks = tasks_resp if isinstance(tasks_resp, list) else []

    def _task_entry(t: dict) -> dict:
        due = (t.get("due_date") or "")[:10]
        return {
            "task_id":    t["id"],
            "title":      t.get("title", "?"),
            "project_id": t.get("project_id"),
            "done":       t.get("done", False),
            "due_date":   due or None,
            "priority":   t.get("priority", 0),
        }

    task_list = [_task_entry(t) for t in tasks]
    done_ct = sum(1 for t in tasks if t.get("done"))
    return ActionResult.success(
        summary=f"Project '{proj_title}': {len(task_list)} task(s), {done_ct} done.",
        data={
            "project_id":    params.project_id,
            "project_title": proj_title,
            "count":         len(task_list),
            "tasks":         task_list,
        },
    )


# ─── get_project ──────────────────────────────────────────────────────────── #

class GetProjectParams(BaseModel):
    project_id: Optional[int] = Field(None, description="Integer project ID.")
    project_name: Optional[str] = Field(
        None,
        description="Project name to look up (e.g. 'webhostmost tasks').",
    )


@chat.function(
    "get_project",
    action_type="read",
    description=(
        "Get metadata for a single project — id, title, description, color, archived status. "
        "Pass project_id OR project_name (e.g. 'WebHostMost Tasks'). "
        "Use when user asks about a specific project or you need its ID from a name."
    ),
    data_model=GetProjectResult,
)
async def get_project(ctx, params: GetProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.")
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.")

    resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch project"))

    return ActionResult.success(
        summary=f"Project #{params.project_id}: {resp.get('title', '?')}.",
        data={
            "project_id":   resp.get("id", params.project_id),
            "title":        resp.get("title", ""),
            "description":  resp.get("description", ""),
            "hex_color":    resp.get("hex_color"),
            "is_archived":  resp.get("is_archived", False),
        },
    )
