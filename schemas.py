"""tasks · Pydantic output schemas.

Every `@sdk_ext.tool` declares an `output_schema`. The Webbee Narrator
grounds prose against these fields (I-TOOL-SCHEMA-REQUIRED). Errors flow
through `ok=False, error=<msg>` in the same shape so the Narrator can
compose a single response across both branches.

Wire contract: field names mirror the vikunja-bridge JSON (v0.4.0) — any
rename must coordinate with `/home/vikunja-bridge/` on api-server.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ─── Shared base ─────────────────────────────────────────────────────── #

class _ToolResult(BaseModel):
    ok: bool = True
    error: str | None = None


# ─── Leaf types ──────────────────────────────────────────────────────── #

class TaskRef(BaseModel):
    """Condensed task for list views."""
    task_id: int
    title: str
    project_id: int | None = None
    done: bool = False
    due_date: str | None = None
    priority: int = 0


class ProjectRef(BaseModel):
    project_id: int
    title: str


class Comment(BaseModel):
    comment_id: int | None = None
    comment: str = ""
    author: str = ""
    created: str | None = None


# ─── Task CRUD outputs ───────────────────────────────────────────────── #

class TaskCreated(_ToolResult):
    task_id: int = 0
    title: str = ""
    project_id: int = 0
    due_date: str | None = None
    priority: int = 0
    bucket_id: int = 0


class TaskUpdated(_ToolResult):
    task_id: int = 0
    title: str = ""
    done: bool = False
    due_date: str | None = None
    priority: int = 0
    percent_done: float = 0.0
    fields_updated: list[str] = Field(default_factory=list)


class TaskCompleted(_ToolResult):
    task_id: int = 0
    done: bool = True


class TaskDeleted(_ToolResult):
    task_id: int = 0
    deleted: bool = True


# ─── Organize outputs ────────────────────────────────────────────────── #

class AssigneeChanged(_ToolResult):
    task_id: int = 0
    assignee_vikunja_user_id: int = 0


class LabelAttached(_ToolResult):
    task_id: int = 0
    label_id: int = 0


class TaskSingleFieldChanged(_ToolResult):
    """Generic envelope for thin set_due_date / set_priority / move_* tools."""
    task_id: int = 0
    title: str = ""
    # Which single field the caller asked to change; mirrors what went on the wire.
    field: str = ""
    # Stringified new value (due_date=ISO, priority=0..5, project_id=int, bucket_id=int).
    value: str = ""


# ─── Project / label outputs ─────────────────────────────────────────── #

class ProjectCreated(_ToolResult):
    project_id: int = 0
    title: str = ""
    hex_color: str | None = None
    parent_project_id: int = 0


class ProjectUpdated(_ToolResult):
    project_id: int = 0
    title: str = ""
    fields_updated: list[str] = Field(default_factory=list)


class ProjectArchived(_ToolResult):
    project_id: int = 0
    is_archived: bool = True


class ProjectDeleted(_ToolResult):
    project_id: int = 0
    deleted: bool = True


class LabelCreated(_ToolResult):
    label_id: int = 0
    title: str = ""
    hex_color: str | None = None


class LabelDeleted(_ToolResult):
    label_id: int = 0
    deleted: bool = True


# ─── Search outputs ──────────────────────────────────────────────────── #

class TaskListResult(_ToolResult):
    count: int = 0
    tasks: list[TaskRef] = Field(default_factory=list)
    page: int = 1
    per_page: int = 0


# ─── Collab outputs ──────────────────────────────────────────────────── #

class CommentAdded(_ToolResult):
    comment_id: int | None = None
    task_id: int = 0
    comment: str = ""


class MentionPosted(_ToolResult):
    comment_id: int | None = None
    task_id: int = 0
    comment: str = ""
    mentioned_username: str = ""


class CommentList(_ToolResult):
    task_id: int = 0
    count: int = 0
    comments: list[Comment] = Field(default_factory=list)
