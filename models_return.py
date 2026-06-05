"""tasks · Typed return models for @chat.function data_model= contracts (SDK 5.2.0 SDL)."""

from typing import Any, List, Optional

from pydantic import BaseModel, model_validator

from imperal_sdk import sdl


# ─── Helpers ──────────────────────────────────────────────────────────────── #

_PRIORITY_MAP: dict[int, Optional[str]] = {
    0: None, 1: "low", 2: "medium", 3: "high", 4: "urgent", 5: "urgent",
}


def vikunja_priority(p: int) -> Optional[str]:
    """Vikunja int priority (0-5) → SDL Prioritized literal."""
    return _PRIORITY_MAP.get(p)


def vikunja_date(raw: Optional[str]) -> Optional[str]:
    """Return ISO string or None for Vikunja null dates (0001-01-01...)."""
    if not raw or raw.startswith("0001"):
        return None
    return raw


# ─── Shared primitives ────────────────────────────────────────────────────── #

class TaskAssignee(BaseModel):
    vikunja_user_id: int
    username: str


class TaskLabelItem(BaseModel):
    label_id: int
    title: str
    hex_color: Optional[str] = None


def vikunja_assignees(raw) -> List[TaskAssignee]:
    """Vikunja task `assignees` array → typed list. Empty list when absent."""
    return [
        TaskAssignee(vikunja_user_id=a.get("id"), username=a.get("username", ""))
        for a in (raw or [])
    ]


def vikunja_labels(raw) -> List[TaskLabelItem]:
    """Vikunja task `labels` array → typed list. Empty list when absent."""
    return [
        TaskLabelItem(label_id=l.get("id"), title=l.get("title", ""), hex_color=l.get("hex_color"))
        for l in (raw or [])
    ]


# ─── SDL Entity types (SDK 5.2.0) ─────────────────────────────────────────── #

class TaskEntity(sdl.Entity, sdl.Completable, sdl.Prioritized, sdl.Schedulable, sdl.Timestamped):
    """Full SDL task entity. id=task_id, title=task title, kind="task"."""
    project_id: Optional[int] = None
    bucket_id: Optional[int] = None
    hex_color: Optional[str] = None
    percent_done: float = 0.0
    is_favorite: bool = False
    assignees: List[TaskAssignee] = []
    labels: List[TaskLabelItem] = []


class ProjectEntity(sdl.Entity, sdl.Progress, sdl.Timestamped):
    """Full SDL project entity. id=project_id, title=project title, kind="project"."""
    hex_color: Optional[str] = None
    is_archived: bool = False


class BucketEntity(sdl.Entity, sdl.Progress):
    """SDL kanban bucket. id=bucket_id, title=bucket title, kind="bucket".
    sdl.Progress provides: total_count (task count), done_count."""
    limit: int = 0
    is_done_bucket: bool = False


# ─── Slim SDL entity types for list items ─────────────────────────────────── #

class TaskItem(sdl.Entity, sdl.Completable, sdl.Prioritized, sdl.Schedulable):
    """Slim SDL task entity for list/search results.

    Carries assignees / labels / percent_done / bucket_id so list reads can
    answer "who is assigned", "which are labeled X", "% done", and "which
    bucket" WITHOUT an N× get_task fan-out. `description` stays off the slim
    item on purpose (HTML body would bloat large lists) — use get_task for it."""
    project_id: Optional[int] = None
    bucket_id: Optional[int] = None
    percent_done: float = 0.0
    assignees: List[TaskAssignee] = []
    labels: List[TaskLabelItem] = []


class SubtaskItem(sdl.Entity, sdl.Completable):
    """Slim SDL task entity for subtask lists."""


class ProjectItem(sdl.Entity):
    """Slim SDL project entity for project list results.

    Carries `is_archived` / `is_favorite` so the narrator can answer
    "show favorited / archived projects" by filtering the facts itself.
    (Progress counts are intentionally NOT here — Vikunja's project object
    has none; computing them needs an N× bucket_counts fan-out, which the
    skeleton already does — answer "% complete" from skeleton context.)"""
    hex_color: Optional[str] = None
    is_archived: bool = False
    is_favorite: bool = False


# ─── handlers_crud ────────────────────────────────────────────────────────── #

class CreateTaskResult(BaseModel):
    task_id: int
    title: str
    project_id: int
    due_date: Optional[str] = None
    priority: int = 0
    bucket_id: Optional[int] = None
    assignee: Optional[str] = None
    refresh_panels: List[str]


class UpdateTaskResult(BaseModel):
    task_id: int
    title: Optional[str] = None
    done: bool = False
    due_date: Optional[str] = None
    priority: int = 0
    percent_done: float = 0.0
    refresh_panels: List[str]


class TaskStatusResult(BaseModel):
    task_id: int
    done: bool
    refresh_panels: List[str]


class DeleteTaskResult(BaseModel):
    task_id: int
    deleted: bool
    refresh_panels: List[str]


class BulkDeleteItem(BaseModel):
    task_id: int
    title: str
    deleted: bool
    error: Optional[str] = None


class BulkDeleteResult(BaseModel):
    deleted_count: int
    failed_count: int
    results: List[BulkDeleteItem]
    refresh_panels: List[str]


class CreateSubtaskResult(BaseModel):
    subtask_id: int
    parent_task_id: int
    title: str
    refresh_panels: List[str]


class ListSubtasksResult(sdl.EntityList[SubtaskItem]):
    """list_subtasks return — a REAL sdl.EntityList[SubtaskItem] (items=[...],
    total=N, x-sdl='entity-list'). Parent task_id carried as an additive typed field."""
    task_id: Optional[int] = None


class ToggleChecklistResult(BaseModel):
    task_id: int
    item_index: int
    checked: bool
    refresh_panels: List[str]


# ─── handlers_search ──────────────────────────────────────────────────────── #

class TaskListResult(sdl.EntityList[TaskItem]):
    """list_my_tasks / list_overdue / list_today / list_upcoming / filter_tasks —
    a REAL sdl.EntityList[TaskItem] (items=[...], total=N, x-sdl='entity-list').
    NO legacy {count, tasks:[dict]} wrapper."""
    pass


class FindTaskResult(sdl.EntityList[TaskItem]):
    """find_task — a REAL sdl.EntityList[TaskItem]; the search query carried as an
    additive typed field."""
    query: str = ""


# ─── handlers_connection ──────────────────────────────────────────────────── #

class VikunjaConnectionResult(BaseModel):
    base_url: Optional[str] = None
    username: Optional[str] = None
    vikunja_user_id: Any = None
    refresh_panels: List[str]


class DisconnectResult(BaseModel):
    deleted: bool
    refresh_panels: List[str]


class ConnectionStatusResult(BaseModel):
    connected: bool
    base_url: Optional[str] = None
    username: Optional[str] = None
    vikunja_user_id: Any = None


# ─── handlers_collab ──────────────────────────────────────────────────────── #

class CommentResult(BaseModel):
    comment_id: Any = None
    task_id: int
    comment: str


class MentionCommentResult(BaseModel):
    comment_id: Any = None
    task_id: int
    comment: str = ""
    mentioned_username: Optional[str] = None


class CommentItem(BaseModel):
    comment_id: Any
    comment: str
    author: str
    created: Optional[str] = None


class ListCommentsResult(BaseModel):
    count: int
    comments: List[CommentItem]


class CommentRefResult(BaseModel):
    comment_id: int
    task_id: int


# ─── handlers_organize ────────────────────────────────────────────────────── #

class UserEntity(sdl.Entity):
    """Vikunja user as a canonical SDL entity (kind='user'): id=vikunja user id,
    title=username. `connected` marks whether the user has linked their own
    Imperal↔Vikunja connection. Mirrors the admin-ext UserRecord pattern."""
    username: str = ""
    connected: bool = False

    @model_validator(mode="before")
    @classmethod
    def _sdl_canon(cls, data):
        if isinstance(data, dict):
            data["id"] = data.get("id") or data.get("vikunja_user_id") or 0
            data.setdefault("title", data.get("username") or data.get("name") or "")
            data.setdefault("kind", "user")
        return data


class SearchUsersResult(sdl.EntityList[UserEntity]):
    """search_vikunja_users return — a REAL sdl.EntityList[UserEntity] (items=[...],
    x-sdl='entity-list'). NO legacy {users:[dict]} wrapper."""
    pass


class ProjectMembersResult(sdl.EntityList[UserEntity]):
    """list_project_members return — a REAL sdl.EntityList[UserEntity]; project_id
    carried as an additive typed field (EntityList is a pydantic BaseModel)."""
    project_id: Optional[int] = None


class AssignResult(BaseModel):
    task_id: int
    assignee_vikunja_user_id: Optional[int] = None
    assignee_name: str = ""
    refresh_panels: List[str]


class UnassignResult(BaseModel):
    task_id: int
    assignee_vikunja_user_id: int
    refresh_panels: List[str]


class TaskLabelResult(BaseModel):
    task_id: int
    label_id: int
    refresh_panels: List[str]


# ─── handlers_structure — projects ────────────────────────────────────────── #

class CreateProjectResult(BaseModel):
    project_id: int
    title: str
    hex_color: Optional[str] = None
    parent_project_id: int
    refresh_panels: List[str]


class UpdateProjectResult(BaseModel):
    project_id: int
    title: Optional[str] = None
    refresh_panels: List[str]


class ArchiveProjectResult(BaseModel):
    project_id: int
    is_archived: bool
    refresh_panels: List[str]


class DeleteProjectResult(BaseModel):
    project_id: int
    deleted: bool
    refresh_panels: List[str]


class ListProjectsResult(sdl.EntityList[ProjectItem]):
    """list_projects — a REAL sdl.EntityList[ProjectItem] (items=[...], total=N,
    x-sdl='entity-list')."""
    pass


# ─── handlers_structure — labels ──────────────────────────────────────────── #

class LabelItem(BaseModel):
    label_id: int
    title: str
    hex_color: Optional[str] = None


class ListLabelsResult(BaseModel):
    count: int
    labels: List[LabelItem]


class CreateLabelResult(BaseModel):
    label_id: int
    title: str
    hex_color: Optional[str] = None
    refresh_panels: List[str]


class DeleteLabelResult(BaseModel):
    label_id: int
    deleted: bool
    refresh_panels: List[str]


# ─── handlers_structure — buckets ─────────────────────────────────────────── #

class ListProjectBucketsResult(BaseModel):
    """list_project_buckets — bucket names, IDs, and task counts."""
    project_id: int
    project_title: str
    bucket_count: int
    buckets: List[BucketEntity]


class CountTasksPerBucketResult(BaseModel):
    """count_tasks_per_bucket — per-bucket and project-level task counts."""
    project_id: int
    project_title: str
    bucket_count: int
    total_tasks: int
    total_done: int
    total_pending: int
    buckets: List[BucketEntity]


class GetBucketTasksResult(sdl.EntityList[TaskItem]):
    """get_bucket_tasks / get_named_bucket_tasks — a REAL sdl.EntityList[TaskItem]
    (items=[...], total=N); bucket coordinates carried as additive typed fields."""
    project_id: Optional[int] = None
    bucket_id: Optional[int] = None
    bucket_title: str = ""


class RenameBucketResult(BaseModel):
    project_id: int
    bucket_id: int
    title: str
    limit: int
    refresh_panels: List[str]


class CreateBucketResult(BaseModel):
    project_id: int
    bucket_id: int
    title: str
    limit: int
    refresh_panels: List[str]


class DeleteBucketResult(BaseModel):
    project_id: int
    bucket_id: int
    deleted: bool
    refresh_panels: List[str]


# ─── handlers_structure — list_project_tasks + get_project ────────────────── #

class ListProjectTasksResult(sdl.EntityList[TaskItem]):
    """list_project_tasks — a REAL sdl.EntityList[TaskItem] (items=[...], total=N);
    project coordinates carried as additive typed fields."""
    project_id: Optional[int] = None
    project_title: str = ""


# ─── handlers_ai ──────────────────────────────────────────────────────────── #

class AiSubtaskCreated(BaseModel):
    task_id: int
    title: str


class AiBreakdownResult(BaseModel):
    task_id: int
    task_title: str
    project_id: Optional[int] = None
    subtasks_created: List[AiSubtaskCreated]
    count: int
    refresh_panels: List[str]
