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

from app import api_get, imperal_id_of, is_no_connection_error
from _task_checklist import _parse_checklist, _strip_tasklist, _toggle_checklist_item  # noqa: F401 — re-exported
from _task_create_form import render_create_form, _priority_options, _header_bar

log = logging.getLogger("tasks.task")


def _iso_to_date(iso: str | None) -> str:
    if not iso or iso.startswith("0001-"):
        return ""
    return iso[:10]


async def render_task_detail(
    ctx,
    task_id: str = "",
    mode: str = "",
    project_id: str = "",
    bucket_id: str = "",
    **kwargs,
):
    imperal_id = imperal_id_of(ctx)
    if not imperal_id:
        return ui.Empty(message="Sign in to use tasks.", icon="UserX")

    if mode == "new":
        return await render_create_form(ctx, project_id, bucket_id)

    if not task_id:
        return ui.Empty(
            message="Select a task on the board, or click + Task to create one.",
            icon="CheckSquare",
        )

    try:
        tid = int(task_id)
    except ValueError:
        return ui.Empty(message=f"Invalid task_id: {task_id}", icon="AlertCircle")

    task = await api_get(ctx, f"/v1/tasks/{tid}", {"imperal_id": imperal_id})
    if isinstance(task, dict) and task.get("status") == "error":
        if is_no_connection_error(task):
            return ui.Empty(
                message="Connect your Vikunja in the sidebar to see this task.",
                icon="Plug",
            )
        return ui.Empty(message=f"Task not found: {task.get('detail')}", icon="AlertCircle")

    if not isinstance(task, dict):
        return ui.Empty(message="Unexpected response from bridge.", icon="AlertCircle")

    comments_raw = await api_get(ctx, f"/v1/tasks/{tid}/comments", {"imperal_id": imperal_id})
    comments = comments_raw if isinstance(comments_raw, list) else []

    if not (task.get("related_tasks") or {}).get("subtask"):
        fallback = await api_get(ctx, f"/v1/tasks/{tid}/subtasks", {"imperal_id": imperal_id})
        if isinstance(fallback, list) and fallback:
            task.setdefault("related_tasks", {})["subtask"] = fallback

    return _render_edit_form(task, comments)


def _render_edit_form(task: dict, comments: list[dict]) -> Any:
    tid = task["id"]
    title = task.get("title") or "?"
    desc = task.get("description") or ""
    due = _iso_to_date(task.get("due_date"))
    prio = task.get("priority") or 0
    done = task.get("done", False)
    project_id = task.get("project_id", 0)

    actions = [
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__editor", note_id=str(project_id), project_id=str(project_id))),
    ]
    if not done:
        actions.append(ui.Button("Complete", icon="Check", variant="primary", size="sm",
                                 on_click=ui.Call("complete_task", task_id=tid)))
    else:
        actions.append(ui.Button("Reopen", icon="RotateCcw", variant="primary", size="sm",
                                 on_click=ui.Call("uncomplete_task", task_id=tid)))
    actions.append(ui.Button("Delete", icon="Trash2", variant="destructive", size="sm",
                             on_click=ui.Call("delete_task", task_id=tid)))

    desc_html = _strip_tasklist(desc) if desc else ""

    edit_form = ui.Form(
        action="update_task",
        submit_label="Save",
        defaults={"task_id": str(tid), "title": title, "due_date": due, "priority": str(prio)},
        children=[
            ui.Input(placeholder="Title", param_name="title"),
            ui.Stack([
                ui.Input(placeholder="Due date (YYYY-MM-DD)", param_name="due_date"),
                ui.Select(param_name="priority", options=_priority_options()),
            ], direction="h", gap=2),
        ],
    )

    desc_edit_form = ui.Form(
        action="update_task",
        submit_label="Save description",
        defaults={"task_id": str(tid), "description": desc},
        children=[
            ui.RichEditor(content=desc, param_name="description",
                          placeholder="Task description — formatting supported…"),
        ],
    )

    comment_items = [
        ui.ListItem(
            id=f"comment_{c.get('id', i)}",
            title=f"@{c.get('author', {}).get('username', '?')}",
            subtitle=c.get("comment", ""),
            actions=[{"icon": "Trash2", "label": "Delete",
                      "on_click": ui.Call("delete_comment", task_id=tid, comment_id=c["id"]),
                      "confirm": "Delete this comment?"}],
        )
        for i, c in enumerate(comments) if c.get("id")
    ]
    comments_card = ui.Card(
        title=f"Comments ({len(comments)})",
        content=ui.Stack([
            ui.List(items=comment_items) if comment_items else ui.Text("No comments yet.", variant="caption"),
            ui.Form(action="add_comment", submit_label="Add comment",
                    defaults={"task_id": str(tid)},
                    children=[ui.Input(placeholder="Write a comment…", param_name="comment")]),
        ], gap=2),
    )

    checklist_items_raw = _parse_checklist(desc)
    cl_done = sum(1 for i in checklist_items_raw if i["checked"])
    cl_total = len(checklist_items_raw)
    checklist_nodes: list = []
    if cl_total:
        cl_list_items = [
            ui.ListItem(
                id=f"cl_{idx}",
                title=("✓ " if item["checked"] else "") + item["text"],
                icon="CheckCircle2" if item["checked"] else "Circle",
                actions=[{"icon": "Check" if not item["checked"] else "RotateCcw",
                          "label": "Mark done" if not item["checked"] else "Uncheck",
                          "on_click": ui.Call("toggle_checklist_item", task_id=tid,
                                             item_index=idx, checked=not item["checked"])}],
            )
            for idx, item in enumerate(checklist_items_raw)
        ]
        checklist_nodes = [ui.Card(
            title=f"Checklist ({cl_done}/{cl_total})",
            content=ui.Stack([
                ui.Progress(value=int(cl_done / cl_total * 100),
                            label=f"{cl_done}/{cl_total} done",
                            color="green" if cl_done == cl_total else "blue"),
                ui.List(items=cl_list_items),
            ], gap=2),
        )]

    related = task.get("related_tasks") or {}
    subtask_list = related.get("subtask") or []
    done_ct = sum(1 for s in subtask_list if s.get("done"))
    total = len(subtask_list)
    sub_items = [
        ui.ListItem(
            id=f"sub_{s['id']}",
            title=("✓ " if s.get("done") else "") + s.get("title", "?"),
            icon="CheckCircle2" if s.get("done") else "Circle",
            on_click=ui.Call("__panel__editor", note_id=str(s["id"]), task_id=str(s["id"])),
            actions=(
                [{"icon": "RotateCcw", "label": "Reopen",
                  "on_click": ui.Call("uncomplete_task", task_id=s["id"])},
                 {"icon": "Trash2", "label": "Delete",
                  "on_click": ui.Call("delete_task", task_id=s["id"]),
                  "confirm": f"Delete '{s.get('title', '?')}'?"}]
                if s.get("done") else
                [{"icon": "Check", "label": "Complete",
                  "on_click": ui.Call("complete_task", task_id=s["id"])},
                 {"icon": "Trash2", "label": "Delete",
                  "on_click": ui.Call("delete_task", task_id=s["id"]),
                  "confirm": f"Delete '{s.get('title', '?')}'?"}]
            ),
        )
        for s in subtask_list
    ]
    progress_nodes = ([ui.Progress(value=int(done_ct / total * 100), label=f"{done_ct}/{total} done",
                                   color="green" if done_ct == total else "blue")]
                      if total else [])
    subtasks_card = ui.Card(
        title=f"Subtasks ({done_ct}/{total})" if total else "Subtasks",
        content=ui.Stack([
            *progress_nodes,
            ui.List(items=sub_items) if sub_items else ui.Text("No subtasks yet.", variant="caption"),
            ui.Form(action="create_subtask", submit_label="Add",
                    defaults={"parent_task_id": str(tid)},
                    children=[ui.Input(placeholder="Subtask title…", param_name="title")]),
        ], gap=2),
    )

    desc_content = ([ui.Html(desc_html, sandbox=False)] if desc_html
                    else [ui.Text("No description.", variant="caption")])
    desc_content += [ui.Divider(), desc_edit_form]

    sections: list = [
        _header_bar(title, actions=actions),
        ui.Card(title="Details", content=edit_form),
        ui.Card(title="Description", content=ui.Stack(desc_content, gap=2)),
        *checklist_nodes,
        subtasks_card,
        comments_card,
    ]
    return ui.Stack(sections, gap=2)
