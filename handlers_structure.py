"""tasks · Structure operations — projects, labels, and kanban buckets."""

import asyncio
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, chat, NoParams, resolve_project_id, fetch_all_pages
from handlers_crud import (
    _require_user,
    _bridge_error_msg,
    _check_batch_size,
    _BULK_CONCURRENCY,
)
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD
from error_codes import (
    TASKS_BRIDGE_ERROR,
    TASKS_BUCKET_NOT_FOUND,
    TASKS_KANBAN_VIEW_MISSING,
    TASKS_LAST_BUCKET,
    TASKS_PROJECT_NOT_FOUND,
)
from models_return import (
    CreateProjectResult,
    UpdateProjectResult,
    ArchiveProjectResult,
    DeleteProjectResult,
    BulkProjectResult,
    LabelItem,
    ListLabelsResult,
    CreateLabelResult,
    DeleteLabelResult,
    ListProjectsResult,
    ListProjectBucketsResult,
    GetBucketTasksResult,
    RenameBucketResult,
    CreateBucketResult,
    DeleteBucketResult,
    ListProjectTasksResult,
    CountTasksPerBucketResult,
    ProjectEntity,
    BucketEntity,
    ProjectItem,
    TaskItem,
    vikunja_priority,
    vikunja_date,
    vikunja_assignees,
    vikunja_labels,
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create project"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error("No fields to update.", code=VALIDATION_MISSING_FIELD)

    resp = await api_post(ctx, f"/v1/projects/{params.project_id}", payload)
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update project"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't archive project"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete project"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch labels"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create label"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete label"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch projects"), code=TASKS_BRIDGE_ERROR)

    projects = resp if isinstance(resp, list) else []
    # Return ALL projects with is_archived/is_favorite flags — let the narrator
    # filter ("show archived/favorited"). Previously archived projects were
    # dropped entirely, which made those questions unanswerable.
    items = [
        ProjectItem(
            id=p["id"],
            title=p.get("title", "?"),
            kind="project",
            hex_color=p.get("hex_color"),
            is_archived=p.get("is_archived", False),
            is_favorite=p.get("is_favorite", False),
        ).model_dump()
        for p in projects
    ]
    active = [p for p in projects if not p.get("is_archived", False)]
    return ActionResult.success(
        summary=f"{len(projects)} project(s), {len(active)} active: "
                f"{', '.join(p.get('title', '?') for p in active[:10])}.",
        data={"items": items, "total": len(items)},
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
        "then use the returned project_id in list_project_buckets, filter_tasks, or create_task."
    ),
    data_model=ListProjectsResult,
)
async def list_projects(ctx, params: NoParams) -> ActionResult:
    return await _list_projects_impl(ctx)


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
    bucket_name: Optional[str] = Field(
        None,
        description="Bucket/column name (e.g. 'Backlog', 'To-Do'). Case-insensitive. Use this OR bucket_id.",
    )
    bucket_id: Optional[int] = Field(
        None,
        description="Integer bucket ID. Use this OR bucket_name.",
    )
    project_name: Optional[str] = Field(
        None,
        description=(
            "Project name (e.g. 'WebHostMost Tasks'). Optional — if omitted, searches across all projects. "
            "Use this OR project_id."
        ),
    )
    project_id: Optional[int] = Field(
        None,
        description="Integer project ID. Use this OR project_name.",
    )


async def _get_kanban_view_id(ctx, imperal_id: str, project_id: int) -> tuple[int | None, ActionResult | None]:
    """Return (view_id, None) or (None, error ActionResult)."""
    views_resp = await api_get(ctx, f"/v1/projects/{project_id}/views", {"imperal_id": imperal_id})
    if isinstance(views_resp, dict) and views_resp.get("status") == "error":
        return None, ActionResult.error(_bridge_error_msg(views_resp, "Couldn't fetch project views"), code=TASKS_BRIDGE_ERROR)
    views = views_resp if isinstance(views_resp, list) else []
    kanban = next((v for v in views if v.get("view_kind") in _KANBAN_VIEW_KINDS), None)
    if kanban is None:
        kinds = [str(v.get("view_kind", "?")) for v in views]
        return None, ActionResult.error(
            f"Project #{project_id} has no kanban (board) view. "
            f"Available view types: {', '.join(kinds) or 'none'}. "
            "Open Vikunja and add a Board view to this project first.",
            code=TASKS_KANBAN_VIEW_MISSING,
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
        "List kanban columns (buckets) for a project — their names, IDs, and task counts. "
        "Use ONLY when the user asks WHAT BUCKETS OR COLUMNS EXIST in a project. "
        "Does NOT return task content — use get_bucket_tasks for that. "
        "Pass project_name (e.g. 'webhostmost tasks') OR project_id."
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
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.", code=VALIDATION_MISSING_FIELD)

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/tasks",
        {"imperal_id": imperal_id},
    )
    if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(buckets_resp, "Couldn't fetch buckets"), code=TASKS_BRIDGE_ERROR)

    buckets = buckets_resp if isinstance(buckets_resp, list) else []

    # Fetch project title for context
    proj_resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    proj_title = proj_resp.get("title", f"#{params.project_id}") if isinstance(proj_resp, dict) else f"#{params.project_id}"

    bucket_entities = [
        BucketEntity(
            id=b["id"],
            title=b.get("title", "?"),
            kind="bucket",
            limit=b.get("limit", 0),
            total_count=len(b.get("tasks") or []),
            is_done_bucket=b.get("is_done_bucket", False),
        )
        for b in buckets
    ]
    names = ", ".join(f"{b.title} ({b.total_count})" for b in bucket_entities)
    return ActionResult.success(
        summary=f"Project '{proj_title}' has {len(bucket_entities)} bucket(s): {names}.",
        data={
            "project_id":    params.project_id,
            "project_title": proj_title,
            "bucket_count":  len(bucket_entities),
            "buckets":       bucket_entities,
        },
    )


@chat.function(
    "get_bucket_tasks",
    action_type="read",
    description=(
        "Get tasks from a specific kanban bucket/column. "
        "Use when the user asks WHAT TASKS ARE IN a named bucket (e.g. 'what tasks are in Backlog?', "
        "'show me the To-Do column', 'tasks in Corporate Tasks bucket'). "
        "Do NOT use to list all buckets — use list_project_buckets for that. "
        "Pass bucket_name (resolved automatically) OR bucket_id. "
        "project_name and project_id are optional — omit to search across all projects."
    ),
    data_model=GetBucketTasksResult,
)
async def get_bucket_tasks(ctx, params: GetBucketTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if not params.bucket_name and not params.bucket_id:
        return ActionResult.error(
            "Pass bucket_name (e.g. 'Backlog') or bucket_id. "
            "Use list_project_buckets to see available buckets.",
            code=VALIDATION_MISSING_FIELD,
        )

    # Resolve project_id from project_name if needed
    project_id = params.project_id
    if project_id is None and params.project_name:
        project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)

    # Build list of project IDs to search
    if project_id is not None:
        project_ids = [project_id]
        project_titles = {project_id: params.project_name or f"#{project_id}"}
    else:
        # No project specified — search all active projects
        projects_resp = await api_get(ctx, "/v1/projects", {"imperal_id": imperal_id})
        projects = [p for p in (projects_resp if isinstance(projects_resp, list) else [])
                    if not p.get("is_archived", False)]
        project_ids = [p["id"] for p in projects]
        project_titles = {p["id"]: p.get("title", f"#{p['id']}") for p in projects}

    # Search across project(s)
    for pid in project_ids:
        view_id, err = await _get_kanban_view_id(ctx, imperal_id, pid)
        if err:
            continue  # skip projects with no kanban view

        buckets_resp = await api_get(
            ctx,
            f"/v1/projects/{pid}/views/{view_id}/tasks",
            {"imperal_id": imperal_id},
        )
        if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
            continue

        buckets = buckets_resp if isinstance(buckets_resp, list) else []

        # Find target bucket by name or ID
        if params.bucket_id is not None:
            target = next((b for b in buckets if b.get("id") == params.bucket_id), None)
        else:
            target = _match_by_name(buckets, params.bucket_name, title_key="title")

        if target is None:
            continue

        def _task_entry(t: dict) -> TaskItem:
            return TaskItem(
                id=t["id"],
                title=t.get("title", "?"),
                kind="task",
                is_done=t.get("done", False),
                priority=vikunja_priority(t.get("priority", 0)),
                due_at=vikunja_date(t.get("due_date")),
                project_id=t.get("project_id"),
                bucket_id=t.get("bucket_id") or None,
                percent_done=t.get("percent_done", 0.0),
                assignees=vikunja_assignees(t.get("assignees")),
                labels=vikunja_labels(t.get("labels")),
            )

        task_list = [_task_entry(t) for t in (target.get("tasks") or [])]
        proj_title = project_titles.get(pid, f"#{pid}")
        return ActionResult.success(
            summary=(
                f"Bucket '{target.get('title', '?')}' in '{proj_title}': "
                f"{len(task_list)} task(s)."
            ),
            data={
                "items":        [t.model_dump() for t in task_list],
                "total":        len(task_list),
                "project_id":   pid,
                "bucket_id":    target["id"],
                "bucket_title": target.get("title", "?"),
            },
        )

    # Nothing found
    bucket_ref = f"'{params.bucket_name}'" if params.bucket_name else f"#{params.bucket_id}"
    proj_ref = f" in '{params.project_name or project_id}'" if (params.project_name or project_id) else " across all projects"
    return ActionResult.error(
        f"Bucket {bucket_ref} not found{proj_ref}. "
        "Call list_project_buckets to see available buckets.",
        code=TASKS_BUCKET_NOT_FOUND,
    )


class CreateBucketParams(BaseModel):
    project_id: int = Field(..., description="Integer project ID from list_projects.")
    title: str = Field(..., min_length=1, max_length=250, description="Column name.")
    limit: Optional[int] = Field(None, ge=0, description="WIP limit (0 = no limit). Omit for unlimited.")


class DeleteBucketParams(BaseModel):
    project_id: int = Field(..., description="Integer project ID.")
    bucket_id: int = Field(..., description="Integer bucket ID from list_project_buckets.")


# ─── count_tasks_per_bucket ───────────────────────────────────────────────── #

class CountTasksParams(BaseModel):
    project_id: Optional[int] = Field(
        None,
        description="Integer project ID. Pass project_name instead if unknown.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Project name (e.g. 'WebHostMost Tasks'). Used when project_id is unknown.",
    )


@chat.function(
    "count_tasks_per_bucket",
    action_type="read",
    description=(
        "Count tasks in every kanban bucket for a project — returns per-bucket totals "
        "(total, done, pending) and project-level totals. "
        "Use when the user asks 'how many tasks', 'сколько задач', "
        "'how many tasks are in each bucket', 'total tasks in project X', 'сколько всего задач'. "
        "Pass project_name (e.g. 'WebHostMost Tasks') or project_id. "
        "Counts are exact — queried directly from the database, no pagination limits."
    ),
    data_model=CountTasksPerBucketResult,
)
async def count_tasks_per_bucket(ctx, params: CountTasksParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.", code=VALIDATION_MISSING_FIELD)

    view_id, err = await _get_kanban_view_id(ctx, imperal_id, params.project_id)
    if err:
        return err

    # Use SQL-based bridge endpoint — bypasses Vikunja's 50-task-per-request cap.
    counts_resp = await api_get(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/bucket_counts",
        {"imperal_id": imperal_id},
    )
    if isinstance(counts_resp, dict) and counts_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(counts_resp, "Couldn't fetch bucket counts"), code=TASKS_BRIDGE_ERROR)

    proj_resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    proj_title = proj_resp.get("title", f"#{params.project_id}") if isinstance(proj_resp, dict) else f"#{params.project_id}"

    bucket_counts = [
        BucketEntity(
            id=b["bucket_id"],
            title=b.get("title", "?"),
            kind="bucket",
            total_count=b["task_count"],
            done_count=b["done_count"],
            is_done_bucket=False,
        )
        for b in (counts_resp if isinstance(counts_resp, list) else [])
    ]

    total_tasks = sum(b.total_count or 0 for b in bucket_counts)
    total_done = sum(b.done_count or 0 for b in bucket_counts)
    lines = [
        f"  {b.title}: {b.total_count} ({(b.total_count or 0) - (b.done_count or 0)} pending, {b.done_count} done)"
        for b in bucket_counts
    ]
    summary = (
        f"Project '{proj_title}': {total_tasks} task(s) total, "
        f"{total_done} done, {total_tasks - total_done} pending.\n" + "\n".join(lines)
    )
    return ActionResult.success(
        summary=summary,
        data={
            "project_id":    params.project_id,
            "project_title": proj_title,
            "bucket_count":  len(bucket_counts),
            "total_tasks":   total_tasks,
            "total_done":    total_done,
            "total_pending": total_tasks - total_done,
            "buckets":       bucket_counts,
        },
    )


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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't rename bucket"), code=TASKS_BRIDGE_ERROR)

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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't create bucket"), code=TASKS_BRIDGE_ERROR)

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

    # Pre-check the >=1-bucket invariant ourselves — Vikunja rejects removing
    # a view's last bucket with a 412, and surfacing that as a clean fact up
    # front reads better than letting the call fail and re-deriving the same
    # thing from the bridge's error detail.
    buckets_resp = await api_get(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/buckets",
        {"imperal_id": imperal_id},
    )
    if isinstance(buckets_resp, dict) and buckets_resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(buckets_resp, "Couldn't fetch buckets"), code=TASKS_BRIDGE_ERROR)
    buckets = buckets_resp if isinstance(buckets_resp, list) else []
    if len(buckets) <= 1:
        return ActionResult.error(
            "Can't delete this bucket — a kanban view must keep at least one bucket. "
            "Create another bucket first if you want to remove it.",
            code=TASKS_LAST_BUCKET,
        )

    resp = await api_delete(
        ctx,
        f"/v1/projects/{params.project_id}/views/{view_id}/buckets/{params.bucket_id}",
        {"imperal_id": imperal_id},
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete bucket"), code=TASKS_BRIDGE_ERROR)

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
        "List tasks in a specific project (paginated — default 50/page, max 200). "
        "Use when the user wants to SEE task titles/details, NOT to count tasks. "
        "For counting ('how many tasks', 'сколько задач') use count_tasks_per_bucket instead — "
        "this function returns a page, not the total. "
        "Pass project_name (e.g. 'WebHostMost Tasks') or project_id."
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
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.", code=VALIDATION_MISSING_FIELD)

    # Fetch project title for summary
    proj_resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    proj_title = proj_resp.get("title", f"#{params.project_id}") if isinstance(proj_resp, dict) else f"#{params.project_id}"

    pf = f"project_id = {params.project_id}"
    if params.filter:
        pf = f"{pf} && {params.filter}"
    base_params: dict = {"imperal_id": imperal_id, "filter": pf}

    # Auto-paginate on default page=1 to return all project tasks.
    if params.page == 1:
        tasks = await fetch_all_pages(ctx, base_params)
        if not tasks:
            resp_check = await api_get(ctx, "/v1/tasks/all", {**base_params, "page": 1, "per_page": 50})
            if isinstance(resp_check, dict) and resp_check.get("status") == "error":
                return ActionResult.error(_bridge_error_msg(resp_check, "Couldn't fetch project tasks"), code=TASKS_BRIDGE_ERROR)
    else:
        query_params = {**base_params, "page": params.page, "per_page": params.per_page}
        tasks_resp = await api_get(ctx, "/v1/tasks/all", query_params)
        if isinstance(tasks_resp, dict) and tasks_resp.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(tasks_resp, "Couldn't fetch project tasks"), code=TASKS_BRIDGE_ERROR)
        tasks = tasks_resp if isinstance(tasks_resp, list) else []

    def _task_entry(t: dict) -> TaskItem:
        return TaskItem(
            id=t["id"],
            title=t.get("title", "?"),
            kind="task",
            is_done=t.get("done", False),
            priority=vikunja_priority(t.get("priority", 0)),
            due_at=vikunja_date(t.get("due_date")),
            project_id=t.get("project_id"),
            bucket_id=t.get("bucket_id") or None,
            percent_done=t.get("percent_done", 0.0),
            assignees=vikunja_assignees(t.get("assignees")),
            labels=vikunja_labels(t.get("labels")),
        )

    task_list = [_task_entry(t) for t in tasks]
    done_ct = sum(1 for t in task_list if t.is_done)
    return ActionResult.success(
        summary=f"Project '{proj_title}': {len(task_list)} task(s) total, {done_ct} done.",
        data={
            "items":         [t.model_dump() for t in task_list],
            "total":         len(task_list),
            "project_id":    params.project_id,
            "project_title": proj_title,
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
    data_model=ProjectEntity,
)
async def get_project(ctx, params: GetProjectParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if params.project_id is None and params.project_name:
        params.project_id = await resolve_project_id(ctx, imperal_id, params.project_name)
        if params.project_id is None:
            return ActionResult.error(f"Project '{params.project_name}' not found.", code=TASKS_PROJECT_NOT_FOUND)
    if params.project_id is None:
        return ActionResult.error("Pass project_id or project_name.", code=VALIDATION_MISSING_FIELD)

    resp = await api_get(ctx, f"/v1/projects/{params.project_id}", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch project"), code=TASKS_BRIDGE_ERROR)

    entity = ProjectEntity(
        id=resp.get("id", params.project_id),
        title=resp.get("title", "") or f"Project #{params.project_id}",
        kind="project",
        description=resp.get("description") or None,
        hex_color=resp.get("hex_color") or None,
        is_archived=resp.get("is_archived", False),
    )
    return ActionResult.success(
        summary=f"Project '{entity.title}' (id={entity.id}).",
        data=entity,
    )


class DeleteProjectsParams(BaseModel):
    project_ids: Optional[List[int]] = Field(
        None,
        description="List of integer project IDs to delete. Use this if you already have the IDs.",
    )
    project_names: Optional[List[str]] = Field(
        None,
        description="List of project names to find and delete (e.g. ['Old board', 'Test']). Auto-resolved to IDs.",
    )
    confirm: bool = Field(
        default=False,
        description="Set true on a second call to actually delete. First call (default) only previews which projects would go.",
    )


@chat.function(
    "delete_projects",
    action_type="destructive",
    effects=["delete:project"],
    event="projects.deleted",
    description=(
        "Permanently delete MULTIPLE projects at once, each with ALL its tasks. Pass project_ids "
        "(list of integers) OR project_names (list of names). Requires an explicit confirm=true on "
        "a second call; the first call only previews which projects would be deleted. Cannot be undone."
    ),
    data_model=BulkProjectResult,
)
async def delete_projects(ctx, params: DeleteProjectsParams) -> ActionResult:
    """Delete a set of projects, each cascading to all of its tasks.

    This one carries a preview gate that `delete_tasks` does not, and the
    asymmetry is deliberate. Deleting a task loses a task; deleting a project
    silently takes every task inside it with no way back. When the caller
    passed *names*, the risk is sharper still — a fuzzy match resolves 'Test'
    to whatever it finds first, so naming the resolved projects back before
    touching anything is the difference between a cleanup and an accident.
    """
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    if not params.project_ids and not params.project_names:
        return ActionResult.error("Pass project_ids or project_names.", code=VALIDATION_MISSING_FIELD)

    oversized = _check_batch_size(
        (params.project_ids or []) + (params.project_names or []), "projects")
    if oversized:
        return oversized

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _resolve(name: str) -> tuple[int, str]:
        async with sem:
            pid = await resolve_project_id(ctx, imperal_id, name)
        return (pid if pid is not None else -1), name

    refs: List[tuple[int, str]] = []
    if params.project_names:
        refs.extend(await asyncio.gather(*(_resolve(n) for n in params.project_names)))
    if params.project_ids:
        refs.extend((pid, f"#{pid}") for pid in params.project_ids)

    found = [(pid, title) for pid, title in refs if pid != -1]
    missing = [title for pid, title in refs if pid == -1]

    if not params.confirm:
        listed = ", ".join(f"{title} (#{pid})" for pid, title in found) or "nothing resolved"
        note = f" Not found, will be skipped: {', '.join(missing)}." if missing else ""
        await ctx.log(
            f"delete_projects: preview only (awaiting confirm) — {len(found)} project(s)",
            level="info",
        )
        return ActionResult.success(
            summary=(
                f"This will permanently delete {len(found)} project(s) AND every task inside "
                f"them: {listed}.{note} This cannot be undone — call again with confirm=true "
                "to go ahead."
            ),
            data={
                "deleted_count": 0,
                "failed_count": 0,
                "results": [
                    {"project_id": pid, "title": title, "deleted": False,
                     "error": "awaiting confirmation"}
                    for pid, title in found
                ],
                "refresh_panels": [],
            },
        )

    async def _delete_one(pid: int, title: str) -> dict:
        async with sem:
            resp = await api_delete(ctx, f"/v1/projects/{pid}", params={"imperal_id": imperal_id})
        if isinstance(resp, dict) and resp.get("status") == "error":
            return {"project_id": pid, "title": title, "deleted": False,
                    "error": _bridge_error_msg(resp, "Couldn't delete project")}
        return {"project_id": pid, "title": title, "deleted": True}

    results = list(await asyncio.gather(*(_delete_one(pid, t) for pid, t in found)))
    results.extend(
        {"project_id": -1, "title": title, "deleted": False, "error": "project not found"}
        for title in missing
    )

    deleted_count = sum(1 for r in results if r["deleted"])
    failed_count = len(results) - deleted_count

    if failed_count == 0:
        summary = f"Deleted {deleted_count} project(s) and all their tasks."
    else:
        broken = ", ".join(f"{r['title']} ({r['error']})" for r in results if not r["deleted"])
        summary = (
            f"Deleted {deleted_count} of {len(results)} project(s) — "
            f"{failed_count} failed: {broken}"
        )

    return ActionResult.success(
        summary=summary,
        data={
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "results": results,
            "refresh_panels": ["sidebar", "editor"],
        },
    )
