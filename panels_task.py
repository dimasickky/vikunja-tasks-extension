"""tasks · Task detail renderer (called by panels_editor, NOT a panel itself).

Modes:
  - mode=new + project_id=N   → blank form to create task in project N
  - task_id=N                 → load task + render editable form with comments
  - empty                     → redirect to board via empty state
"""
from __future__ import annotations

import logging
from typing import Any

from imperal_sdk import ui

from app import api_get, _imperal_id, is_no_connection_error

log = logging.getLogger("tasks.task")


# ─── Helpers ───────────────────────────────────────────────────────────── #

def _iso_to_date(iso: str | None) -> str:
    if not iso or iso.startswith("0001-"):
        return ""
    return iso[:10]


def _priority_options():
    return [
        {"value": "0", "label": "0 — none"},
        {"value": "1", "label": "1 — low"},
        {"value": "2", "label": "2 — medium"},
        {"value": "3", "label": "3 — high"},
        {"value": "4", "label": "4 — urgent"},
        {"value": "5", "label": "5 — critical"},
    ]


# ─── Entry point (called by panels_editor at module level) ─────────────── #

async def render_task_detail(
    ctx,
    task_id: str = "",
    mode: str = "",
    project_id: str = "",
    **kwargs,
):
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return ui.Empty(message="Sign in to use tasks.", icon="UserX")

    # ── Create mode ───────────────────────────────────────────────────
    if mode == "new":
        return await _render_create_form(ctx, project_id)

    # ── Edit mode ─────────────────────────────────────────────────────
    if not task_id:
        return ui.Empty(
            message="Select a task on the board, or click + Task to create one.",
            icon="CheckSquare",
        )

    try:
        tid = int(task_id)
    except ValueError:
        return ui.Empty(message=f"Invalid task_id: {task_id}", icon="AlertCircle")

    task = await api_get(f"/v1/tasks/{tid}", {"imperal_id": imperal_id})
    if isinstance(task, dict) and task.get("status") == "error":
        if is_no_connection_error(task):
            return ui.Empty(
                message="Connect your Vikunja in the sidebar to see this task.",
                icon="Plug",
            )
        return ui.Empty(
            message=f"Task not found: {task.get('detail')}", icon="AlertCircle",
        )

    if not isinstance(task, dict):
        return ui.Empty(message="Unexpected response from bridge.", icon="AlertCircle")

    comments_raw = await api_get(
        f"/v1/tasks/{tid}/comments", {"imperal_id": imperal_id},
    )
    comments = comments_raw if isinstance(comments_raw, list) else []

    return _render_edit_form(task, comments)


# ─── Create form ──────────────────────────────────────────────────────── #

async def _render_create_form(ctx, project_id: str) -> Any:
    imperal_id = _imperal_id(ctx)

    # No project selected → show project picker
    if not project_id:
        projects_resp = await api_get("/v1/projects", {"imperal_id": imperal_id})
        projects = [p for p in (projects_resp if isinstance(projects_resp, list) else [])
                    if not p.get("is_archived", False)]
        if not projects:
            return ui.Empty(message="No projects yet — create one in the sidebar.", icon="Folder")
        return ui.Stack([
            _header_bar("New Task — Pick a project"),
            ui.Card(
                title="Select project",
                content=ui.Stack([
                    ui.Button(
                        p.get("title", f"#{p['id']}"),
                        icon="Folder",
                        variant="ghost",
                        size="sm",
                        on_click=ui.Call(
                            "__panel__editor",
                            note_id="new",
                            mode="new",
                            project_id=str(p["id"]),
                        ),
                    )
                    for p in projects
                ], gap=1),
            ),
        ], gap=2)

    pid = int(project_id)

    # Fetch buckets for bucket selector
    bucket_options: list = []
    views_resp = await api_get(f"/v1/projects/{pid}/views", {"imperal_id": imperal_id})
    if isinstance(views_resp, list):
        kanban = next((v for v in views_resp if v.get("view_kind") == "kanban"), None)
        if kanban:
            # /tasks returns buckets with embedded tasks under the tasks PAT scope.
            # /buckets requires a separate Vikunja PAT scope not minted during connect.
            buckets_resp = await api_get(
                f"/v1/projects/{pid}/views/{kanban['id']}/tasks",
                {"imperal_id": imperal_id},
            )
            if isinstance(buckets_resp, list):
                bucket_options = [
                    {"value": str(b["id"]), "label": b.get("title", f"Bucket #{b['id']}")}
                    for b in buckets_resp
                ]

    form_children = [
        ui.Input(placeholder="Task title", param_name="title"),
        ui.Input(placeholder="Description (optional, markdown)", param_name="description"),
        ui.Input(placeholder="Due date (YYYY-MM-DD)", param_name="due_date"),
        ui.Select(param_name="priority", options=_priority_options()),
    ]
    if bucket_options:
        form_children.append(
            ui.Select(param_name="bucket_id", options=bucket_options),
        )

    return ui.Stack([
        _header_bar("New Task"),
        ui.Card(
            title="Create Task",
            content=ui.Stack([
                ui.Form(
                    action="create_task",
                    submit_label="Create",
                    defaults={"project_id": pid},
                    children=form_children,
                ),
                ui.Button(
                    "Cancel",
                    variant="ghost",
                    size="sm",
                    on_click=ui.Call(
                        "__panel__editor",
                        note_id="board",
                        project_id=project_id,
                    ),
                ),
            ], gap=2),
        ),
    ], gap=2)


# ─── Edit form ────────────────────────────────────────────────────────── #

def _render_edit_form(task: dict, comments: list[dict]) -> Any:
    tid = task["id"]
    title = task.get("title") or "?"
    desc = task.get("description") or ""
    due = _iso_to_date(task.get("due_date"))
    prio = task.get("priority") or 0
    done = task.get("done", False)
    project_id = task.get("project_id", 0)

    # Action bar (back / complete / delete — outside the form)
    actions = [
        ui.Button(
            "Back",
            icon="ArrowLeft",
            variant="ghost",
            size="sm",
            on_click=ui.Call(
                "__panel__editor",
                note_id=str(project_id),
                project_id=str(project_id),
            ),
        ),
    ]
    if not done:
        actions.append(
            ui.Button(
                "Complete",
                icon="Check",
                variant="primary",
                size="sm",
                on_click=ui.Call("complete_task", task_id=tid),
            ),
        )
    actions.append(
        ui.Button(
            "Delete",
            icon="Trash2",
            variant="destructive",
            size="sm",
            on_click=ui.Call("delete_task", task_id=tid),
        ),
    )

    # Edit form — task_id passed via defaults (not a visible field)
    edit_form = ui.Form(
        action="update_task",
        submit_label="Save",
        defaults={
            "task_id": str(tid),
            "title": title,
            "description": desc,
            "due_date": due,
            "priority": str(prio),
        },
        children=[
            ui.Input(placeholder="Title", param_name="title"),
            ui.Input(placeholder="Description", param_name="description"),
            ui.Stack([
                ui.Input(
                    placeholder="Due date (YYYY-MM-DD)",
                    param_name="due_date",
                ),
                ui.Select(
                    param_name="priority",
                    options=_priority_options(),
                ),
            ], direction="h", gap=2),
        ],
    )

    # Comments
    comment_items = [
        ui.ListItem(
            id=f"comment_{c.get('id', i)}",
            title=f"@{c.get('author', {}).get('username', '?')}",
            subtitle=c.get("comment", ""),
        )
        for i, c in enumerate(comments)
    ]
    comments_card = ui.Card(
        title=f"Comments ({len(comments)})",
        content=ui.Stack([
            ui.List(items=comment_items) if comment_items
            else ui.Text("No comments yet.", variant="caption"),
            ui.Form(
                action="add_comment",
                submit_label="Add comment",
                defaults={"task_id": str(tid)},
                children=[
                    ui.Input(placeholder="Write a comment…", param_name="comment"),
                ],
            ),
        ], gap=2),
    )

    return ui.Stack([
        _header_bar(title, actions=actions),
        ui.Card(title="Details", content=edit_form),
        comments_card,
    ], gap=2)


# ─── Header bar ────────────────────────────────────────────────────────── #

def _header_bar(title: str, actions: list | None = None) -> Any:
    row = [ui.Text(title, variant="h3")]
    if actions:
        row.append(ui.Stack(actions, direction="h", gap=1))
    return ui.Stack(row, direction="h", sticky=True)
