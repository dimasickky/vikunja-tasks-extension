"""tasks · TasksExtension — class-based v2.0 tool surface.

25 `@sdk_ext.tool` methods spanning task CRUD, projects, labels, organize
ops, list/filter search, and collaboration comments. Thin wrappers over
the vikunja-bridge HTTP client in ``app`` — business logic lives here,
wire contract stays frozen.

Error pattern: every tool catches the generic bridge error envelope
(`{status: error, detail: <msg>}`) and returns its output_schema with
`ok=False, error=<msg>`. Exceptions from the HTTP layer are similarly
flattened so the Narrator always receives a typed shape.

Destructive ops (`delete_task`, `delete_project`, `delete_label`) carry
`cost_credits=1` so the pre-ACK confirmation gate always fires before
dispatch.
"""
from __future__ import annotations

import logging

from imperal_sdk import Extension, ext as sdk_ext

from schemas import (
    AssigneeChanged,
    Comment,
    CommentAdded,
    CommentList,
    LabelAttached,
    LabelCreated,
    LabelDeleted,
    MentionPosted,
    ProjectArchived,
    ProjectCreated,
    ProjectDeleted,
    ProjectUpdated,
    TaskCompleted,
    TaskCreated,
    TaskDeleted,
    TaskListResult,
    TaskRef,
    TaskSingleFieldChanged,
    TaskUpdated,
)

log = logging.getLogger("tasks.tools")


def _err(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


# ─── TasksExtension ───────────────────────────────────────────────────── #

class TasksExtension(Extension):
    """Vikunja-backed kanban / project manager.

    Backend: vikunja-bridge (api-server:8102) → Vikunja (api-server:3456).
    All mutations carry `imperal_id` in the JSON body; list ops put it in
    query params — the bridge uses it to resolve the Vikunja user id and
    mint a per-request JWT. Wire contract is frozen.
    """

    app_id = "tasks"

    # ── Require user helper ───────────────────────────────────────────── #

    @staticmethod
    def _uid(ctx) -> str:
        from app import _imperal_id
        uid = _imperal_id(ctx)
        if not uid:
            raise RuntimeError(
                "No authenticated user on context. Tasks extension needs a "
                "provisioned imperal_id to talk to vikunja-bridge.",
            )
        return uid

    # ── Task CRUD ─────────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description=(
            "Create a new task in a project (kanban board). Optional fields: "
            "description, due_date (ISO 8601), priority (0..5), bucket_id."
        ),
        output_schema=TaskCreated,
        scopes=["tasks:write"],
    )
    async def create_task(
        self,
        ctx,
        project_id: int,
        title: str,
        description: str = "",
        due_date: str | None = None,
        priority: int | None = None,
        bucket_id: int | None = None,
    ) -> TaskCreated:
        from app import api_post

        try:
            payload: dict = {
                "imperal_id":   self._uid(ctx),
                "project_id":   int(project_id),
                "title":        title,
                "description":  description,
            }
            if due_date is not None:
                payload["due_date"] = due_date
            if priority is not None:
                payload["priority"] = int(priority)
            if bucket_id is not None:
                payload["bucket_id"] = int(bucket_id)

            resp = await api_post("/v1/tasks", payload)
            if resp.get("status") == "error":
                return TaskCreated(ok=False, error=str(resp.get("detail", "")))
            return TaskCreated(
                task_id=int(resp["id"]),
                title=resp.get("title", title),
                project_id=int(resp.get("project_id", project_id)),
                due_date=resp.get("due_date"),
                priority=int(resp.get("priority", 0)),
                bucket_id=int(resp.get("bucket_id", 0)),
            )
        except Exception as e:
            return TaskCreated(ok=False, error=_err(e))

    @sdk_ext.tool(
        description=(
            "Update any fields of a task: title, description, due_date, "
            "start_date, end_date, priority, percent_done, bucket_id, "
            "project_id (moves the task), hex_color. Unspecified args are "
            "left untouched."
        ),
        output_schema=TaskUpdated,
        scopes=["tasks:write"],
    )
    async def update_task(
        self,
        ctx,
        task_id: int,
        title: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        priority: int | None = None,
        percent_done: float | None = None,
        bucket_id: int | None = None,
        project_id: int | None = None,
        hex_color: str | None = None,
    ) -> TaskUpdated:
        from app import api_post

        try:
            payload: dict = {"imperal_id": self._uid(ctx)}
            fields = {
                "title": title, "description": description,
                "due_date": due_date, "start_date": start_date, "end_date": end_date,
                "priority": priority, "percent_done": percent_done,
                "bucket_id": bucket_id, "project_id": project_id,
                "hex_color": hex_color,
            }
            for k, v in fields.items():
                if v is not None:
                    payload[k] = v
            if len(payload) == 1:
                return TaskUpdated(
                    ok=False, error="No fields to update", task_id=int(task_id),
                )

            resp = await api_post(f"/v1/tasks/{int(task_id)}", payload)
            if resp.get("status") == "error":
                return TaskUpdated(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id),
                )
            return TaskUpdated(
                task_id=int(resp.get("id", task_id)),
                title=resp.get("title", ""),
                done=resp.get("done", False),
                due_date=resp.get("due_date"),
                priority=int(resp.get("priority", 0)),
                percent_done=float(resp.get("percent_done", 0.0)),
                fields_updated=[k for k in payload if k != "imperal_id"],
            )
        except Exception as e:
            return TaskUpdated(ok=False, error=_err(e), task_id=int(task_id))

    @sdk_ext.tool(
        description="Mark a task as done (done=true, percent_done=1.0).",
        output_schema=TaskCompleted,
        scopes=["tasks:write"],
    )
    async def complete_task(self, ctx, task_id: int) -> TaskCompleted:
        from app import api_post

        try:
            resp = await api_post(
                f"/v1/tasks/{int(task_id)}",
                {"imperal_id": self._uid(ctx), "done": True, "percent_done": 1.0},
            )
            if resp.get("status") == "error":
                return TaskCompleted(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id), done=False,
                )
            return TaskCompleted(task_id=int(task_id), done=True)
        except Exception as e:
            return TaskCompleted(
                ok=False, error=_err(e), task_id=int(task_id), done=False,
            )

    @sdk_ext.tool(
        description=(
            "Permanently delete a task. Cannot be undone — always confirm "
            "with the user before calling."
        ),
        output_schema=TaskDeleted,
        scopes=["tasks:write"],
        cost_credits=1,
    )
    async def delete_task(self, ctx, task_id: int) -> TaskDeleted:
        from app import api_delete

        try:
            resp = await api_delete(
                f"/v1/tasks/{int(task_id)}", params={"imperal_id": self._uid(ctx)},
            )
            if resp.get("status") == "error":
                return TaskDeleted(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id), deleted=False,
                )
            return TaskDeleted(task_id=int(task_id), deleted=True)
        except Exception as e:
            return TaskDeleted(
                ok=False, error=_err(e), task_id=int(task_id), deleted=False,
            )

    # ── Project CRUD ──────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description=(
            "Create a new project (kanban board). Optional parent_project_id "
            "for nesting and hex_color (e.g. 'ff5500', without '#')."
        ),
        output_schema=ProjectCreated,
        scopes=["tasks:write"],
    )
    async def create_project(
        self,
        ctx,
        title: str,
        description: str = "",
        parent_project_id: int | None = None,
        hex_color: str | None = None,
    ) -> ProjectCreated:
        from app import api_post

        try:
            payload: dict = {
                "imperal_id": self._uid(ctx),
                "title":      title,
                "description": description,
            }
            if parent_project_id is not None:
                payload["parent_project_id"] = int(parent_project_id)
            if hex_color is not None:
                payload["hex_color"] = hex_color

            resp = await api_post("/v1/projects", payload)
            if resp.get("status") == "error":
                return ProjectCreated(ok=False, error=str(resp.get("detail", "")))
            return ProjectCreated(
                project_id=int(resp["id"]),
                title=resp.get("title", title),
                hex_color=resp.get("hex_color"),
                parent_project_id=int(resp.get("parent_project_id", 0)),
            )
        except Exception as e:
            return ProjectCreated(ok=False, error=_err(e))

    @sdk_ext.tool(
        description="Update a project's title, description, or hex_color.",
        output_schema=ProjectUpdated,
        scopes=["tasks:write"],
    )
    async def update_project(
        self,
        ctx,
        project_id: int,
        title: str | None = None,
        description: str | None = None,
        hex_color: str | None = None,
    ) -> ProjectUpdated:
        from app import api_post

        try:
            payload: dict = {"imperal_id": self._uid(ctx)}
            for k, v in (("title", title), ("description", description), ("hex_color", hex_color)):
                if v is not None:
                    payload[k] = v
            if len(payload) == 1:
                return ProjectUpdated(
                    ok=False, error="No fields to update",
                    project_id=int(project_id),
                )
            resp = await api_post(f"/v1/projects/{int(project_id)}", payload)
            if resp.get("status") == "error":
                return ProjectUpdated(
                    ok=False, error=str(resp.get("detail", "")),
                    project_id=int(project_id),
                )
            return ProjectUpdated(
                project_id=int(resp.get("id", project_id)),
                title=resp.get("title", ""),
                fields_updated=[k for k in payload if k != "imperal_id"],
            )
        except Exception as e:
            return ProjectUpdated(
                ok=False, error=_err(e), project_id=int(project_id),
            )

    @sdk_ext.tool(
        description=(
            "Archive a project (is_archived=true) — hide from active views "
            "but preserve all data. Use delete_project to purge permanently."
        ),
        output_schema=ProjectArchived,
        scopes=["tasks:write"],
    )
    async def archive_project(self, ctx, project_id: int) -> ProjectArchived:
        from app import api_post

        try:
            resp = await api_post(
                f"/v1/projects/{int(project_id)}",
                {"imperal_id": self._uid(ctx), "is_archived": True},
            )
            if resp.get("status") == "error":
                return ProjectArchived(
                    ok=False, error=str(resp.get("detail", "")),
                    project_id=int(project_id), is_archived=False,
                )
            return ProjectArchived(project_id=int(project_id), is_archived=True)
        except Exception as e:
            return ProjectArchived(
                ok=False, error=_err(e),
                project_id=int(project_id), is_archived=False,
            )

    @sdk_ext.tool(
        description=(
            "Permanently delete a project with all its tasks (cascade). "
            "Cannot be undone — always confirm with the user."
        ),
        output_schema=ProjectDeleted,
        scopes=["tasks:write"],
        cost_credits=1,
    )
    async def delete_project(self, ctx, project_id: int) -> ProjectDeleted:
        from app import api_delete

        try:
            resp = await api_delete(
                f"/v1/projects/{int(project_id)}",
                params={"imperal_id": self._uid(ctx)},
            )
            if resp.get("status") == "error":
                return ProjectDeleted(
                    ok=False, error=str(resp.get("detail", "")),
                    project_id=int(project_id), deleted=False,
                )
            return ProjectDeleted(project_id=int(project_id), deleted=True)
        except Exception as e:
            return ProjectDeleted(
                ok=False, error=_err(e),
                project_id=int(project_id), deleted=False,
            )

    # ── Label CRUD ────────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description="Create a new label with a title and optional hex color.",
        output_schema=LabelCreated,
        scopes=["tasks:write"],
    )
    async def create_label(
        self,
        ctx,
        title: str,
        description: str = "",
        hex_color: str | None = None,
    ) -> LabelCreated:
        from app import api_post

        try:
            payload: dict = {
                "imperal_id":  self._uid(ctx),
                "title":       title,
                "description": description,
            }
            if hex_color is not None:
                payload["hex_color"] = hex_color
            resp = await api_post("/v1/labels", payload)
            if resp.get("status") == "error":
                return LabelCreated(ok=False, error=str(resp.get("detail", "")))
            return LabelCreated(
                label_id=int(resp["id"]),
                title=resp.get("title", title),
                hex_color=resp.get("hex_color"),
            )
        except Exception as e:
            return LabelCreated(ok=False, error=_err(e))

    @sdk_ext.tool(
        description=(
            "Permanently delete a label — also removes it from every task "
            "that currently carries it."
        ),
        output_schema=LabelDeleted,
        scopes=["tasks:write"],
        cost_credits=1,
    )
    async def delete_label(self, ctx, label_id: int) -> LabelDeleted:
        from app import api_delete

        try:
            resp = await api_delete(
                f"/v1/labels/{int(label_id)}",
                params={"imperal_id": self._uid(ctx)},
            )
            if resp.get("status") == "error":
                return LabelDeleted(
                    ok=False, error=str(resp.get("detail", "")),
                    label_id=int(label_id), deleted=False,
                )
            return LabelDeleted(label_id=int(label_id), deleted=True)
        except Exception as e:
            return LabelDeleted(
                ok=False, error=_err(e),
                label_id=int(label_id), deleted=False,
            )

    # ── Organize ──────────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description="Assign a Vikunja user as an assignee to a task.",
        output_schema=AssigneeChanged,
        scopes=["tasks:write"],
    )
    async def assign_task(
        self, ctx, task_id: int, assignee_vikunja_user_id: int,
    ) -> AssigneeChanged:
        from app import api_post

        try:
            resp = await api_post(
                f"/v1/tasks/{int(task_id)}/assign",
                {
                    "imperal_id": self._uid(ctx),
                    "assignee_vikunja_user_id": int(assignee_vikunja_user_id),
                },
            )
            if resp.get("status") == "error":
                return AssigneeChanged(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id),
                    assignee_vikunja_user_id=int(assignee_vikunja_user_id),
                )
            return AssigneeChanged(
                task_id=int(task_id),
                assignee_vikunja_user_id=int(assignee_vikunja_user_id),
            )
        except Exception as e:
            return AssigneeChanged(
                ok=False, error=_err(e),
                task_id=int(task_id),
                assignee_vikunja_user_id=int(assignee_vikunja_user_id),
            )

    @sdk_ext.tool(
        description="Remove a Vikunja user from a task's assignees.",
        output_schema=AssigneeChanged,
        scopes=["tasks:write"],
    )
    async def unassign_task(
        self, ctx, task_id: int, assignee_vikunja_user_id: int,
    ) -> AssigneeChanged:
        from app import api_delete

        try:
            resp = await api_delete(
                f"/v1/tasks/{int(task_id)}/assign/{int(assignee_vikunja_user_id)}",
                params={"imperal_id": self._uid(ctx)},
            )
            if resp.get("status") == "error":
                return AssigneeChanged(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id),
                    assignee_vikunja_user_id=int(assignee_vikunja_user_id),
                )
            return AssigneeChanged(
                task_id=int(task_id),
                assignee_vikunja_user_id=int(assignee_vikunja_user_id),
            )
        except Exception as e:
            return AssigneeChanged(
                ok=False, error=_err(e),
                task_id=int(task_id),
                assignee_vikunja_user_id=int(assignee_vikunja_user_id),
            )

    @sdk_ext.tool(
        description="Attach an existing label to a task by its label_id.",
        output_schema=LabelAttached,
        scopes=["tasks:write"],
    )
    async def add_label(self, ctx, task_id: int, label_id: int) -> LabelAttached:
        from app import api_post

        try:
            resp = await api_post(
                f"/v1/tasks/{int(task_id)}/labels",
                {"imperal_id": self._uid(ctx), "label_id": int(label_id)},
            )
            if resp.get("status") == "error":
                return LabelAttached(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id), label_id=int(label_id),
                )
            return LabelAttached(task_id=int(task_id), label_id=int(label_id))
        except Exception as e:
            return LabelAttached(
                ok=False, error=_err(e),
                task_id=int(task_id), label_id=int(label_id),
            )

    @sdk_ext.tool(
        description="Detach a label from a task without deleting the label itself.",
        output_schema=LabelAttached,
        scopes=["tasks:write"],
    )
    async def remove_label(
        self, ctx, task_id: int, label_id: int,
    ) -> LabelAttached:
        from app import api_delete

        try:
            resp = await api_delete(
                f"/v1/tasks/{int(task_id)}/labels/{int(label_id)}",
                params={"imperal_id": self._uid(ctx)},
            )
            if resp.get("status") == "error":
                return LabelAttached(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id), label_id=int(label_id),
                )
            return LabelAttached(task_id=int(task_id), label_id=int(label_id))
        except Exception as e:
            return LabelAttached(
                ok=False, error=_err(e),
                task_id=int(task_id), label_id=int(label_id),
            )

    async def _single_field_update(
        self, ctx, task_id: int, field: str, value_for_wire, human_value: str,
    ) -> TaskSingleFieldChanged:
        """Shared backbone for set_due_date / set_priority / move_* tools."""
        from app import api_post

        try:
            resp = await api_post(
                f"/v1/tasks/{int(task_id)}",
                {"imperal_id": self._uid(ctx), field: value_for_wire},
            )
            if resp.get("status") == "error":
                return TaskSingleFieldChanged(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id), field=field, value=human_value,
                )
            return TaskSingleFieldChanged(
                task_id=int(resp.get("id", task_id)),
                title=resp.get("title", ""),
                field=field,
                value=human_value,
            )
        except Exception as e:
            return TaskSingleFieldChanged(
                ok=False, error=_err(e),
                task_id=int(task_id), field=field, value=human_value,
            )

    @sdk_ext.tool(
        description=(
            "Set or change the due date of a task. Use ISO 8601 UTC format "
            "(e.g. 2026-04-25T12:00:00Z)."
        ),
        output_schema=TaskSingleFieldChanged,
        scopes=["tasks:write"],
    )
    async def set_due_date(
        self, ctx, task_id: int, due_date: str,
    ) -> TaskSingleFieldChanged:
        return await self._single_field_update(
            ctx, task_id, "due_date", due_date, due_date,
        )

    @sdk_ext.tool(
        description=(
            "Set task priority 0 (none) to 5 (critical). 1=low, 2=medium, "
            "3=high, 4=urgent, 5=critical."
        ),
        output_schema=TaskSingleFieldChanged,
        scopes=["tasks:write"],
    )
    async def set_priority(
        self, ctx, task_id: int, priority: int,
    ) -> TaskSingleFieldChanged:
        p = max(0, min(int(priority), 5))
        return await self._single_field_update(
            ctx, task_id, "priority", p, str(p),
        )

    @sdk_ext.tool(
        description="Move a task to a different project (kanban board).",
        output_schema=TaskSingleFieldChanged,
        scopes=["tasks:write"],
    )
    async def move_to_project(
        self, ctx, task_id: int, project_id: int,
    ) -> TaskSingleFieldChanged:
        return await self._single_field_update(
            ctx, task_id, "project_id", int(project_id), str(int(project_id)),
        )

    @sdk_ext.tool(
        description="Move a task to a different kanban bucket (column).",
        output_schema=TaskSingleFieldChanged,
        scopes=["tasks:write"],
    )
    async def move_to_bucket(
        self, ctx, task_id: int, bucket_id: int,
    ) -> TaskSingleFieldChanged:
        return await self._single_field_update(
            ctx, task_id, "bucket_id", int(bucket_id), str(int(bucket_id)),
        )

    # ── Search / list ─────────────────────────────────────────────────── #

    async def _fetch_tasks(
        self,
        ctx,
        filter_expr: str | None,
        sort_by: str | None,
        search: str | None,
        page: int,
        per_page: int,
    ) -> TaskListResult:
        from app import api_get

        try:
            page = max(1, int(page))
            per_page = max(1, min(int(per_page), 200))

            q: dict = {
                "imperal_id": self._uid(ctx),
                "page":       page,
                "per_page":   per_page,
            }
            if filter_expr:
                q["filter"] = filter_expr
            if sort_by:
                q["sort_by"] = sort_by
            if search:
                q["s"] = search

            resp = await api_get("/v1/tasks/all", q)
            if isinstance(resp, dict) and resp.get("status") == "error":
                return TaskListResult(
                    ok=False, error=str(resp.get("detail", "")),
                    page=page, per_page=per_page,
                )
            raw = resp if isinstance(resp, list) else []
            return TaskListResult(
                count=len(raw),
                tasks=[
                    TaskRef(
                        task_id=int(t["id"]),
                        title=t.get("title", ""),
                        project_id=t.get("project_id"),
                        done=t.get("done", False),
                        due_date=t.get("due_date"),
                        priority=int(t.get("priority", 0)),
                    ) for t in raw
                ],
                page=page,
                per_page=per_page,
            )
        except Exception as e:
            return TaskListResult(
                ok=False, error=_err(e), page=page, per_page=per_page,
            )

    @sdk_ext.tool(
        description=(
            "List the user's tasks with optional Vikunja filter syntax, "
            "sort key, and free-text search. Example filter: "
            "'done = false && priority >= 3 && due_date < now + 7d'."
        ),
        output_schema=TaskListResult,
        scopes=["tasks:read"],
    )
    async def list_my_tasks(
        self,
        ctx,
        filter: str | None = None,  # noqa: A002  (wire name)
        sort_by: str | None = None,
        search: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> TaskListResult:
        return await self._fetch_tasks(ctx, filter, sort_by, search, page, per_page)

    @sdk_ext.tool(
        description=(
            "List every overdue task (done=false AND due_date in the past). "
            "Sorted by due_date ascending, oldest first."
        ),
        output_schema=TaskListResult,
        scopes=["tasks:read"],
    )
    async def list_overdue(self, ctx) -> TaskListResult:
        return await self._fetch_tasks(
            ctx,
            "done = false && due_date < now && due_date > 1970-01-01",
            "due_date",
            None,
            1,
            200,
        )

    @sdk_ext.tool(
        description=(
            "List every task due today — done=false AND due_date between "
            "start-of-day and end-of-day. Sorted by priority descending."
        ),
        output_schema=TaskListResult,
        scopes=["tasks:read"],
    )
    async def list_today(self, ctx) -> TaskListResult:
        return await self._fetch_tasks(
            ctx,
            "done = false && due_date >= now/d && due_date < now/d+1d",
            "priority",
            None,
            1,
            200,
        )

    @sdk_ext.tool(
        description=(
            "Filter tasks with a Vikunja expression. Operators: = != > < >= "
            "<= in like. Logical: && ||. Time helpers: now, now/d, now+7d, "
            "now-3d. Fields: title, description, done, due_date, start_date, "
            "end_date, priority, project_id, percent_done."
        ),
        output_schema=TaskListResult,
        scopes=["tasks:read"],
    )
    async def filter_tasks(
        self,
        ctx,
        filter: str,  # noqa: A002
        page: int = 1,
        per_page: int = 50,
    ) -> TaskListResult:
        return await self._fetch_tasks(ctx, filter, None, None, page, per_page)

    # ── Collaboration ─────────────────────────────────────────────────── #

    @sdk_ext.tool(
        description="Add a comment to a task. Markdown is supported.",
        output_schema=CommentAdded,
        scopes=["tasks:write"],
    )
    async def add_comment(
        self, ctx, task_id: int, comment: str,
    ) -> CommentAdded:
        from app import api_post

        try:
            resp = await api_post(
                f"/v1/tasks/{int(task_id)}/comments",
                {"imperal_id": self._uid(ctx), "comment": comment},
            )
            if resp.get("status") == "error":
                return CommentAdded(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id), comment=comment,
                )
            return CommentAdded(
                comment_id=resp.get("id"),
                task_id=int(task_id),
                comment=resp.get("comment", comment),
            )
        except Exception as e:
            return CommentAdded(
                ok=False, error=_err(e),
                task_id=int(task_id), comment=comment,
            )

    @sdk_ext.tool(
        description=(
            "Mention a user in a task comment. Vikunja auto-links '@username' "
            "and sends a notification. Pass message='' to post a plain mention."
        ),
        output_schema=MentionPosted,
        scopes=["tasks:write"],
    )
    async def mention_user(
        self, ctx, task_id: int, username: str, message: str = "",
    ) -> MentionPosted:
        text = f"@{username}" if not message else f"{message}\n\n@{username}"
        added = await self.add_comment(ctx, task_id=int(task_id), comment=text)
        return MentionPosted(
            ok=added.ok,
            error=added.error,
            comment_id=added.comment_id,
            task_id=int(task_id),
            comment=added.comment,
            mentioned_username=username,
        )

    @sdk_ext.tool(
        description="List every comment on a task in chronological order.",
        output_schema=CommentList,
        scopes=["tasks:read"],
    )
    async def list_comments(self, ctx, task_id: int) -> CommentList:
        from app import api_get

        try:
            resp = await api_get(
                f"/v1/tasks/{int(task_id)}/comments",
                {"imperal_id": self._uid(ctx)},
            )
            if isinstance(resp, dict) and resp.get("status") == "error":
                return CommentList(
                    ok=False, error=str(resp.get("detail", "")),
                    task_id=int(task_id),
                )
            raw = resp if isinstance(resp, list) else []
            return CommentList(
                task_id=int(task_id),
                count=len(raw),
                comments=[
                    Comment(
                        comment_id=c.get("id"),
                        comment=c.get("comment", ""),
                        author=(c.get("author", {}) or {}).get("username", ""),
                        created=c.get("created"),
                    ) for c in raw
                ],
            )
        except Exception as e:
            return CommentList(
                ok=False, error=_err(e), task_id=int(task_id),
            )
