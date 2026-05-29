"""tasks · Typed return models for @chat.function data_model= contracts (SDK 5.0.1)."""

from typing import Any, List, Optional

from pydantic import BaseModel


# ─── handlers_crud ────────────────────────────────────────────────────────── #

class CreateTaskResult(BaseModel):
    task_id: int
    title: str
    project_id: int
    due_date: Optional[str] = None
    priority: int = 0
    bucket_id: Optional[int] = None   # None = default bucket; never 0 (ambiguous)
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


class CreateSubtaskResult(BaseModel):
    subtask_id: int
    parent_task_id: int
    title: str
    refresh_panels: List[str]


class SubtaskItem(BaseModel):
    task_id: int
    title: str
    done: bool


class ListSubtasksResult(BaseModel):
    task_id: int
    subtasks: List[SubtaskItem]


class ToggleChecklistResult(BaseModel):
    task_id: int
    item_index: int
    checked: bool
    refresh_panels: List[str]


# ─── handlers_crud (get_task) ─────────────────────────────────────────────── #

class TaskAssignee(BaseModel):
    vikunja_user_id: int
    username: str


class TaskLabelItem(BaseModel):
    label_id: int
    title: str
    hex_color: Optional[str] = None


class GetTaskResult(BaseModel):
    task_id: int
    title: str
    description: str
    done: bool
    due_date: Optional[str] = None
    start_date: Optional[str] = None
    priority: int
    percent_done: float
    project_id: int
    bucket_id: Optional[int] = None
    hex_color: Optional[str] = None
    is_favorite: bool = False
    assignees: List[TaskAssignee]
    labels: List[TaskLabelItem]
    created: Optional[str] = None
    updated: Optional[str] = None


# ─── handlers_search ──────────────────────────────────────────────────────── #

class TaskItem(BaseModel):
    task_id: int
    title: str
    project_id: Optional[int]
    done: bool
    due_date: Optional[str]
    priority: int


class TaskListResult(BaseModel):
    count: int
    tasks: List[TaskItem]


class FindTaskResult(BaseModel):
    count: int
    query: str
    tasks: List[TaskItem]


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

class SearchUsersResult(BaseModel):
    users: List[Any]


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


# ─── handlers_structure ───────────────────────────────────────────────────── #

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


class ProjectItem(BaseModel):
    project_id: int
    title: str
    hex_color: Optional[str]


class ListProjectsResult(BaseModel):
    count: int
    projects: List[ProjectItem]


class BucketTaskItem(BaseModel):
    task_id: int
    title: str
    done: bool
    priority: int
    due_date: Optional[str]


class BucketItem(BaseModel):
    bucket_id: int
    title: str
    limit: int
    task_count: int
    tasks: List[BucketTaskItem]


class ListBucketsResult(BaseModel):
    project_id: int
    buckets: List[BucketItem]


# ─── Tier-2: focused bucket endpoints ────────────────────────────────────── #

class BucketNavItem(BaseModel):
    """Lightweight bucket descriptor with task count."""
    bucket_id: int
    title: str
    limit: int
    task_count: int = 0
    is_done_bucket: bool


class ListProjectBucketsResult(BaseModel):
    """Result of list_project_buckets — bucket names, IDs, and task counts."""
    project_id: int
    project_title: str
    bucket_count: int
    buckets: List[BucketNavItem]


class BucketCountItem(BaseModel):
    bucket_id: int
    title: str
    task_count: int
    done_count: int
    pending_count: int
    is_done_bucket: bool


class CountTasksPerBucketResult(BaseModel):
    """Result of count_tasks_per_bucket — per-bucket and project-level task counts."""
    project_id: int
    project_title: str
    bucket_count: int
    total_tasks: int
    total_done: int
    total_pending: int
    buckets: List[BucketCountItem]


class GetBucketTasksResult(BaseModel):
    """Result of get_bucket_tasks / get_named_bucket_tasks."""
    project_id: int
    bucket_id: int
    bucket_title: str
    task_count: int
    tasks: List[BucketTaskItem]


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


# ─── handlers_structure (new: list_project_tasks + get_project) ──────────── #

class ListProjectTasksResult(BaseModel):
    project_id: int
    project_title: str
    total_count: int
    tasks: List[TaskItem]


class GetProjectResult(BaseModel):
    project_id: int
    title: str
    description: str
    hex_color: Optional[str] = None
    is_archived: bool = False


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
