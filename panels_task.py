"""tasks · Task detail panel (slot=center, when task selected or creating).

Modes:
  - mode=new + project_id=N   → blank form to create task in project N
  - task_id=N                 → load task + render editable form with comments
  - empty                     → redirect to board via empty state
"""
from __future__ import annotations

import logging
from typing import Any

from imperal_sdk import ui

from app import ext, api_get, _imperal_id

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


# ─── Panel ─────────────────────────────────────────────────────────────── #

@ext.panel(
    "task",
    slot="center",
    title="Task",
    icon="CheckSquare",
    refresh=(
        "on_event:task.updated,task.completed,task.commented,"
        "task.labeled,task.unlabeled,task.assigned,task.unassigned"
    ),
)
async def task_detail(
    ctx,
    task_id: str = "",
    mode: str = "",
    project_id: str = "",
    **kwargs,
):
    """Task detail editor + comments. `mode=new` renders blank create form."""
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return ui.Empty(message="Not provisioned yet", icon="UserX")

    # ── Create mode ───────────────────────────────────────────────────
    if mode == "new":
        return _render_create_form(project_id)

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
        return ui.Empty(
            message=f"Task not found: {task.get('detail')}", icon="AlertCircle",
        )

    # Fetch comments inline
    comments_raw = await api_get(
        f"/v1/tasks/{tid}/comments", {"imperal_id": imperal_id},
    )
    comments = comments_raw if isinstance(comments_raw, list) else []

    return _render_edit_form(task, comments)


# ─── Create form ──────────────────────────────────────────────────────── #

def _render_create_form(project_id: str) -> Any:
    if not project_id:
        return ui.Empty(
            message="Open a project first to add a task to it.",
            icon="Folder",
        )

    return ui.Stack([
        _header_bar("New Task"),
        ui.Card(
            title="Create Task",
            content=ui.Stack([
                ui.Input(placeholder="Task title", param_name="title"),
                ui.Input(
                    placeholder="Description (optional, markdown)",
                    param_name="description",
                ),
                ui.Input(
                    placeholder="Due date (YYYY-MM-DDTHH:MM:SSZ, optional)",
                    param_name="due_date",
                ),
                ui.Select(
                    param_name="priority",
                    options=_priority_options(),
                    value="0",
                ),
                ui.Stack([
                    ui.Button(
                        "Create",
                        icon="Check",
                        variant="primary",
                        size="sm",
                        on_click=ui.Call(
                            "create_task",
                            project_id=int(project_id),
                        ),
                    ),
                    ui.Button(
                        "Cancel",
                        variant="ghost",
                        size="sm",
                        on_click=ui.Call("__panel__board", project_id=project_id),
                    ),
                ], direction="horizontal", gap=1),
            ], gap=2),
        ),
    ], gap=2)


# ─── Edit form ────────────────────────────────────────────────────────── #

def _render_edit_form(task: dict, comments: list[dict]) -> Any:
    tid = task["id"]
    title = task.get("title", "?")
    desc = task.get("description", "")
    due = _iso_to_date(task.get("due_date"))
    prio = task.get("priority", 0)
    done = task.get("done", False)
    percent = float(task.get("percent_done", 0.0))
    project_id = task.get("project_id", 0)

    # Action bar
    actions = [
        ui.Button(
            "Back",
            icon="ArrowLeft",
            variant="ghost",
            size="sm",
            on_click=ui.Call("__panel__board", project_id=str(project_id)),
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

    # Main form
    form_content = ui.Stack([
        ui.Input(value=title, placeholder="Title", param_name="title"),
        ui.Input(value=desc, placeholder="Description", param_name="description"),
        ui.Stack([
            ui.Input(
                value=due,
                placeholder="Due date (YYYY-MM-DD)",
                param_name="due_date",
            ),
            ui.Select(
                param_name="priority",
                options=_priority_options(),
                value=str(prio),
            ),
        ], direction="horizontal", gap=2),
        ui.Input(
            value=f"{int(percent * 100)}",
            placeholder="Progress % (0-100)",
            param_name="percent_done_display",
        ),
        ui.Button(
            "Save",
            icon="Save",
            variant="primary",
            size="sm",
            on_click=ui.Call("update_task", task_id=tid),
        ),
    ], gap=2)

    # Comments section
    comment_items = [
        ui.ListItem(
            title=f"@{c.get('author', {}).get('username', '?')}",
            subtitle=c.get("comment", ""),
        )
        for c in comments
    ]
    comments_card = ui.Card(
        title=f"Comments ({len(comments)})",
        content=ui.Stack([
            ui.List(children=comment_items) if comment_items else ui.Text("No comments yet.", variant="caption"),
            ui.Input(placeholder="Write a comment…", param_name="comment"),
            ui.Button(
                "Add comment",
                icon="MessageSquarePlus",
                variant="secondary",
                size="sm",
                on_click=ui.Call("add_comment", task_id=tid),
            ),
        ], gap=2),
    )

    return ui.Stack([
        _header_bar(title, actions=actions),
        ui.Card(title="Details", content=form_content),
        comments_card,
    ], gap=2)


# ─── Header bar ────────────────────────────────────────────────────────── #

def _header_bar(title: str, actions: list | None = None) -> Any:
    row = [ui.Text(title, variant="h3")]
    if actions:
        row.append(ui.Stack(actions, direction="horizontal", gap=1))
    return ui.Stack(row, direction="horizontal", sticky=True)
