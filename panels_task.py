"""tasks · Task detail renderer (called by panels_editor, NOT a panel itself).

Modes:
  - mode=new + project_id=N   → blank form to create task in project N
  - task_id=N                 → load task + render editable form with comments
  - empty                     → redirect to board via empty state
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

from imperal_sdk import ui

from app import api_get, imperal_id_of, is_no_connection_error

log = logging.getLogger("tasks.task")


# ─── TipTap checklist parser ──────────────────────────────────────────── #

class _ChecklistParser(HTMLParser):
    """Extract taskItem entries from Vikunja's TipTap HTML description."""

    def __init__(self):
        super().__init__()
        self._in_item = False
        self._in_div = False
        self._current_checked = False
        self._current_text: list[str] = []
        self.items: list[dict] = []  # [{"checked": bool, "text": str}]

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if tag == "li" and attrs_d.get("data-type") == "taskItem":
            self._in_item = True
            self._current_checked = attrs_d.get("data-checked") == "true"
            self._current_text = []
        elif tag == "div" and self._in_item:
            self._in_div = True

    def handle_endtag(self, tag):
        if tag == "li" and self._in_item:
            text = "".join(self._current_text).strip()
            if text:
                self.items.append({"checked": self._current_checked, "text": text})
            self._in_item = False
            self._in_div = False
        elif tag == "div":
            self._in_div = False

    def handle_data(self, data):
        if self._in_div:
            self._current_text.append(data)


def _parse_checklist(html: str) -> list[dict]:
    """Return list of {checked, text} from TipTap taskList HTML."""
    if not html or "taskList" not in html:
        return []
    parser = _ChecklistParser()
    parser.feed(html)
    return parser.items


def _toggle_checklist_item(html: str, index: int, checked: bool) -> str:
    """Return description HTML with item at `index` toggled to `checked`."""
    pattern = r'(<li data-type="taskItem" data-checked=")(?:true|false)(")'
    items_found = list(re.finditer(pattern, html))
    if index >= len(items_found):
        return html
    m = items_found[index]
    new_val = "true" if checked else "false"
    return html[:m.start()] + m.group(1) + new_val + m.group(2) + html[m.end():]


def _strip_tasklist(html: str) -> str:
    """Remove TipTap taskList blocks from HTML — we render them as DUI elements."""
    return re.sub(r'<ul[^>]*data-type=["\']taskList["\'][^>]*>.*?</ul>', "", html,
                  flags=re.DOTALL).strip()


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
    imperal_id = imperal_id_of(ctx)
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

    task = await api_get(ctx, f"/v1/tasks/{tid}", {"imperal_id": imperal_id})
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
        ctx, f"/v1/tasks/{tid}/comments", {"imperal_id": imperal_id},
    )
    comments = comments_raw if isinstance(comments_raw, list) else []

    # Fallback: if Vikunja didn't embed related_tasks in the task response,
    # fetch subtasks explicitly so the detail panel is never silently empty.
    if not (task.get("related_tasks") or {}).get("subtask"):
        fallback = await api_get(ctx, f"/v1/tasks/{tid}/subtasks", {"imperal_id": imperal_id})
        if isinstance(fallback, list) and fallback:
            task.setdefault("related_tasks", {})["subtask"] = fallback

    return _render_edit_form(task, comments)


# ─── Create form ──────────────────────────────────────────────────────── #

async def _render_create_form(ctx, project_id: str) -> Any:
    imperal_id = imperal_id_of(ctx)

    # No project selected → show project picker
    if not project_id:
        projects_resp = await api_get(ctx, "/v1/projects", {"imperal_id": imperal_id})
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
    views_resp = await api_get(ctx, f"/v1/projects/{pid}/views", {"imperal_id": imperal_id})
    if isinstance(views_resp, list):
        kanban = next((v for v in views_resp if v.get("view_kind") == "kanban"), None)
        if kanban:
            # /tasks returns buckets with embedded tasks under the tasks PAT scope.
            # /buckets requires a separate Vikunja PAT scope not minted during connect.
            buckets_resp = await api_get(
                ctx,
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

    # Rendered description (HTML stripped of taskList — shown separately as checklist)
    desc_html = _strip_tasklist(desc) if desc else ""

    # Edit form — title, due_date, priority only (description edited separately)
    edit_form = ui.Form(
        action="update_task",
        submit_label="Save",
        defaults={
            "task_id": str(tid),
            "title": title,
            "due_date": due,
            "priority": str(prio),
        },
        children=[
            ui.Input(placeholder="Title", param_name="title"),
            ui.Stack([
                ui.Input(placeholder="Due date (YYYY-MM-DD)", param_name="due_date"),
                ui.Select(param_name="priority", options=_priority_options()),
            ], direction="h", gap=2),
        ],
    )

    # Description edit form (separate card to keep the main form clean)
    desc_edit_form = ui.Form(
        action="update_task",
        submit_label="Save description",
        defaults={"task_id": str(tid), "description": desc},
        children=[ui.Input(placeholder="Description (HTML/markdown)", param_name="description")],
    )

    # Comments
    comment_items = [
        ui.ListItem(
            id=f"comment_{c.get('id', i)}",
            title=f"@{c.get('author', {}).get('username', '?')}",
            subtitle=c.get("comment", ""),
            actions=[
                {"icon": "Trash2", "label": "Delete",
                 "on_click": ui.Call("delete_comment",
                                     task_id=tid, comment_id=c["id"]),
                 "confirm": "Delete this comment?"},
            ],
        )
        for i, c in enumerate(comments)
        if c.get("id")
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

    # TipTap checklist (items stored in description HTML, not task relations)
    checklist_items_raw = _parse_checklist(desc)
    cl_done = sum(1 for i in checklist_items_raw if i["checked"])
    cl_total = len(checklist_items_raw)
    checklist_nodes: list = []
    if cl_total:
        if cl_total:
            checklist_nodes.append(ui.Progress(
                value=int(cl_done / cl_total * 100),
                label=f"{cl_done}/{cl_total} done",
                color="green" if cl_done == cl_total else "blue",
            ))
        cl_list_items = [
            ui.ListItem(
                id=f"cl_{idx}",
                title=("✓ " if item["checked"] else "") + item["text"],
                icon="CheckCircle2" if item["checked"] else "Circle",
                actions=[
                    {
                        "icon": "Check" if not item["checked"] else "RotateCcw",
                        "label": "Mark done" if not item["checked"] else "Uncheck",
                        "on_click": ui.Call(
                            "toggle_checklist_item",
                            task_id=tid,
                            item_index=idx,
                            checked=not item["checked"],
                        ),
                    }
                ],
            )
            for idx, item in enumerate(checklist_items_raw)
        ]
        checklist_card = ui.Card(
            title=f"Checklist ({cl_done}/{cl_total})",
            content=ui.Stack([*checklist_nodes, ui.List(items=cl_list_items)], gap=2),
        )
        checklist_nodes = [checklist_card]

    # Subtasks (task relations with relation_kind=subtask)
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
                [
                    {"icon": "Trash2", "label": "Delete",
                     "on_click": ui.Call("delete_task", task_id=s["id"]),
                     "confirm": f"Delete '{s.get('title', '?')}'?"},
                ]
                if s.get("done") else
                [
                    {"icon": "Check", "label": "Complete",
                     "on_click": ui.Call("complete_task", task_id=s["id"])},
                    {"icon": "Trash2", "label": "Delete",
                     "on_click": ui.Call("delete_task", task_id=s["id"]),
                     "confirm": f"Delete '{s.get('title', '?')}'?"},
                ]
            ),
        )
        for s in subtask_list
    ]
    progress_nodes: list = []
    if total:
        progress_nodes.append(ui.Progress(
            value=int(done_ct / total * 100),
            label=f"{done_ct}/{total} done",
            color="green" if done_ct == total else "blue",
        ))
    subtasks_card = ui.Card(
        title=f"Subtasks ({done_ct}/{total})" if total else "Subtasks",
        content=ui.Stack([
            *progress_nodes,
            ui.List(items=sub_items) if sub_items else ui.Text("No subtasks yet.", variant="caption"),
            ui.Form(
                action="create_subtask",
                submit_label="Add",
                defaults={"parent_task_id": str(tid)},
                children=[ui.Input(placeholder="Subtask title…", param_name="title")],
            ),
        ], gap=2),
    )

    # Description card: rendered HTML view + inline edit form
    desc_content_nodes: list = []
    if desc_html:
        desc_content_nodes.append(ui.Html(desc_html, sandbox=False))
    else:
        desc_content_nodes.append(ui.Text("No description.", variant="caption"))
    desc_content_nodes.append(ui.Divider())
    desc_content_nodes.append(desc_edit_form)

    sections: list = [
        _header_bar(title, actions=actions),
        ui.Card(title="Details", content=edit_form),
        ui.Card(title="Description", content=ui.Stack(desc_content_nodes, gap=2)),
    ]
    if checklist_nodes:
        sections.extend(checklist_nodes)
    sections.append(subtasks_card)
    sections.append(comments_card)

    return ui.Stack(sections, gap=2)


# ─── Header bar ────────────────────────────────────────────────────────── #

def _header_bar(title: str, actions: list | None = None) -> Any:
    row = [ui.Text(title, variant="h3")]
    if actions:
        row.append(ui.Stack(actions, direction="h", gap=1))
    return ui.Stack(row, direction="h", sticky=True)
