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

    attachments_raw = await api_get(ctx, f"/v1/tasks/{tid}/attachments", {"imperal_id": imperal_id})
    attachments = attachments_raw if isinstance(attachments_raw, list) else []

    all_labels_raw = await api_get(ctx, "/v1/labels", {"imperal_id": imperal_id})
    all_labels = all_labels_raw if isinstance(all_labels_raw, list) else []

    if not (task.get("related_tasks") or {}).get("subtask"):
        fallback = await api_get(ctx, f"/v1/tasks/{tid}/subtasks", {"imperal_id": imperal_id})
        if isinstance(fallback, list) and fallback:
            task.setdefault("related_tasks", {})["subtask"] = fallback

    return _render_edit_form(task, comments, attachments, all_labels)


def _render_edit_form(
    task: dict,
    comments: list[dict],
    attachments: list[dict] | None = None,
    all_labels: list[dict] | None = None,
) -> Any:
    tid = task["id"]
    title = task.get("title") or "?"
    desc = task.get("description") or ""
    due = _iso_to_date(task.get("due_date"))
    prio = task.get("priority") or 0
    done = task.get("done", False)
    project_id = task.get("project_id", 0)

    actions = [
        ui.Button("Back", icon="ArrowLeft", variant="ghost", size="sm",
                  on_click=ui.Call("__panel__editor", note_id=str(project_id), project_id=str(project_id),
                                   task_id="", mode="", bucket_id="")),
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
            on_click=ui.Call("__panel__editor", note_id=str(s["id"]), task_id=str(s["id"]),
                             mode="", bucket_id="", view=""),
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

    assignees_card = _assignees_section(tid, task.get("assignees") or [])
    labels_card = _labels_section(tid, task.get("labels") or [], all_labels or [])
    attachments_card = _attachments_section(tid, attachments or [])

    sections: list = [
        _header_bar(title, actions=actions),
        ui.Card(title="Details", content=edit_form),
        assignees_card,
        labels_card,
        ui.Card(title="Description", content=ui.Stack(desc_content, gap=2)),
        *checklist_nodes,
        attachments_card,
        subtasks_card,
        comments_card,
    ]
    return ui.Stack(sections, gap=2)


def _assignees_section(tid: int, assignees: list[dict]) -> Any:
    """Assign/unassign card — shows current assignees with a remove action and
    a query input that resolves to a Vikunja user via assign_task's own
    server-side lookup (same as chat: pass assignee_query, no id needed)."""
    items = [
        ui.ListItem(
            id=f"assignee_{a.get('id')}",
            title=a.get("username", "?"),
            icon="User",
            avatar=ui.Avatar(fallback=(a.get("username") or "?")[:1].upper()),
            actions=[{
                "icon": "X",
                "label": "Unassign",
                "on_click": ui.Call("unassign_task", task_id=tid, assignee_vikunja_user_id=a.get("id")),
                "confirm": f"Unassign {a.get('username', 'this user')}?",
            }],
        )
        for a in assignees if a.get("id")
    ]
    return ui.Card(
        title=f"Assignees ({len(items)})",
        content=ui.Stack([
            ui.List(items=items) if items else ui.Text("Unassigned.", variant="caption"),
            ui.Input(
                placeholder="Assign by name or email, press Enter…",
                param_name="assignee_query",
                on_submit=ui.Call("assign_task", task_id=tid, assignee_query="{{value}}"),
            ),
        ], gap=2),
    )


def _labels_section(tid: int, labels: list[dict], all_labels: list[dict]) -> Any:
    """Label attach/detach card. Detach is a direct button per chip; attach is a
    Select of every label on the instance that isn't already on this task —
    friendlier than typing a numeric label_id, while still calling add_label
    with the real label_id under the hood (Vikunja addresses labels by id)."""
    items = [
        ui.ListItem(
            id=f"label_{l.get('id')}",
            title=l.get("title", "?"),
            icon="Tag",
            badge=ui.Badge(label=l.get("title", "?"), color="blue"),
            actions=[{
                "icon": "X",
                "label": "Remove label",
                "on_click": ui.Call("remove_label", task_id=tid, label_id=l.get("id")),
                "confirm": f"Remove label '{l.get('title', '?')}'?",
            }],
        )
        for l in labels if l.get("id")
    ]
    attached_ids = {l.get("id") for l in labels}
    available = [l for l in all_labels if l.get("id") not in attached_ids]
    footer: list = []
    if available:
        footer.append(ui.Select(
            options=[{"value": str(l["id"]), "label": l.get("title", "?")} for l in available],
            placeholder="Attach a label…",
            param_name="label_id",
            on_change=ui.Call("add_label", task_id=tid, label_id="{{value}}"),
        ))
    elif not items:
        footer.append(ui.Text("No labels exist yet — create one via chat (create_label).", variant="caption"))
    return ui.Card(
        title=f"Labels ({len(items)})",
        content=ui.Stack([
            ui.List(items=items) if items else ui.Text("No labels.", variant="caption"),
            *footer,
        ], gap=2),
    )


def _attachments_section(tid: int, attachments: list[dict]) -> Any:
    """Upload/list/delete card — thin panel wrapper over upload_task_attachment/
    list_task_attachments/delete_task_attachment. Files stream straight to the
    user's own Vikunja instance; this extension never persists file bytes."""
    def _fmt_size(n) -> str:
        if not isinstance(n, (int, float)) or n <= 0:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f}{unit}"
            n /= 1024
        return f"{n:.0f}TB"

    items = [
        ui.ListItem(
            id=f"attachment_{a.get('attachment_id')}",
            title=a.get("filename", "file"),
            subtitle=_fmt_size(a.get("size")),
            icon="Paperclip",
            actions=[{
                "icon": "Trash2",
                "label": "Delete",
                "on_click": ui.Call("delete_task_attachment", task_id=tid, attachment_id=a.get("attachment_id")),
                "confirm": f"Delete attachment '{a.get('filename', 'file')}'?",
            }],
        )
        for a in attachments if a.get("attachment_id")
    ]
    return ui.Card(
        title=f"Attachments ({len(items)})",
        content=ui.Stack([
            ui.List(items=items) if items else ui.Text("No attachments yet.", variant="caption"),
            ui.FileUpload(
                param_name="files",
                multiple=True,
                max_size_mb=20,
                title="Attach files",
                hint="Up to 20MB each — stored on your own Vikunja instance.",
                on_upload=ui.Call("upload_task_attachment", task_id=tid),
            ),
        ], gap=2),
    )
