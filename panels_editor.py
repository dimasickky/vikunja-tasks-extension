"""tasks · Kanban board panel (slot=center, default view).

Renders project tasks grouped by bucket. Uses Vikunja native Kanban view —
one view per project, auto-created by Vikunja with default_bucket_id and
done_bucket_id. Tasks with bucket_id = done_bucket_id are marked done.

Board views:
  - view=today     → filter_tasks by due today, grouped by bucket
  - view=upcoming  → filter_tasks by due in 7d, grouped by bucket
  - view=overdue   → filter_tasks by overdue, single column
  - project_id=N   → show project N's Kanban (default)
  - empty          → show onboarding / first project prompt
"""
from __future__ import annotations

import logging
from typing import Any

from imperal_sdk import ui

from app import ext, api_get, imperal_id_of, is_no_connection_error
from panels_task import render_task_detail, _parse_checklist

log = logging.getLogger("tasks.board")


# ─── Helpers ───────────────────────────────────────────────────────────── #

def _priority_label(p: int) -> str:
    return {0: "", 1: "low", 2: "med", 3: "high", 4: "urgent", 5: "critical"}.get(p, "")


def _due_badge(task: dict) -> str | None:
    d = task.get("due_date") or ""
    if not d or d.startswith("0001-"):
        return None
    # Show first 10 chars (YYYY-MM-DD)
    return d[:10]


def _collect_child_task_ids(all_tasks: list[dict]) -> set[int]:
    """Set of task ids that appear as `related_tasks.subtask` of any task in the list."""
    child_ids: set[int] = set()
    for t in all_tasks:
        for s in (t.get("related_tasks") or {}).get("subtask") or []:
            sid = s.get("id")
            if sid:
                child_ids.add(sid)
    return child_ids


def _split_top_and_children(tasks: list[dict], child_ids: set[int]) -> tuple[list[dict], list[dict]]:
    top = [t for t in tasks if t["id"] not in child_ids]
    children = [t for t in tasks if t["id"] in child_ids]
    return top, children


def _subtasks_section(children: list[dict]) -> Any:
    sub_done = sum(1 for c in children if c.get("done"))
    return ui.Section(
        title=f"↳ Subtasks ({sub_done}/{len(children)})",
        collapsible=True,
        children=[_task_card(c) for c in children],
    )


def _task_card(task: dict) -> Any:
    title = task.get("title", "?")
    tid = task["id"]
    prio = task.get("priority", 0)
    due = _due_badge(task)
    done = task.get("done", False)
    pct = task.get("percent_done", 0.0)

    subtasks = (task.get("related_tasks") or {}).get("subtask") or []
    sub_total = len(subtasks)
    sub_done = sum(1 for s in subtasks if s.get("done"))

    meta_parts = []
    if due:
        meta_parts.append(f"📅 {due}")
    if prio >= 3:
        meta_parts.append(f"⚠ {_priority_label(prio)}")
    if sub_total:
        meta_parts.append(f"☑ {sub_done}/{sub_total}")

    badge = None
    if sub_total and not done:
        color = "green" if sub_done == sub_total else "blue"
        badge = ui.Badge(label=f"{sub_done}/{sub_total}", color=color)
    elif not done and pct > 0:
        badge = ui.Badge(label=f"{int(pct * 100)}%", color="blue")

    return ui.ListItem(
        id=f"task_{tid}",
        title=("✓ " if done else "") + title,
        subtitle=" · ".join(meta_parts) if meta_parts else None,
        icon="CheckCircle2" if done else "Circle",
        badge=badge,
        on_click=ui.Call("__panel__editor", note_id=str(tid), task_id=str(tid)),
    )


async def _find_kanban_view(ctx, imperal_id: str, project_id: int) -> dict | None:
    """Locate the Kanban view of a project. Vikunja auto-creates one per project."""
    views = await api_get(ctx, f"/v1/projects/{project_id}/views", {"imperal_id": imperal_id})
    if not isinstance(views, list):
        return None
    # Vikunja returns view_kind as string in older versions, integer (4) in v0.21+.
    for v in views:
        if v.get("view_kind") in {"kanban", 4}:
            return v
    return None


# ─── Panel ─────────────────────────────────────────────────────────────── #

@ext.panel(
    "editor",
    slot="center",
    title="Board",
    icon="Kanban",
    refresh=(
        "on_event:tasks.task.created,tasks.task.updated,tasks.task.completed,"
        "tasks.task.uncompleted,tasks.task.deleted,"
        "tasks.task.moved,tasks.task.bucket_changed,tasks.task.due_changed,"
        "tasks.task.priority_changed,tasks.task.commented,tasks.task.mentioned,"
        "tasks.task.labeled,tasks.task.unlabeled,"
        "tasks.task.assigned,tasks.task.unassigned,"
        "tasks.project.created,tasks.project.updated,"
        "tasks.project.archived,tasks.project.deleted"
    ),
)
async def tasks_board(
    ctx,
    project_id: str = "",
    view: str = "",
    task_id: str = "",
    mode: str = "",
    bucket_id: str = "",
    **kwargs,
):
    """Single center panel: board, smart view, task detail, create form, or bucket management."""
    imperal_id = imperal_id_of(ctx)

    if not imperal_id:
        return ui.Empty(message="Sign in to use tasks.", icon="UserX")

    # ── Task detail / create form ─────────────────────────────────────
    if task_id or mode == "new":
        return await render_task_detail(
            ctx, task_id=task_id, mode=mode, project_id=project_id, bucket_id=bucket_id,
        )

    # ── Smart views ───────────────────────────────────────────────────
    if view in ("today", "upcoming", "overdue"):
        return await _render_smart_view(ctx, imperal_id, view)

    # ── Project-specific board ────────────────────────────────────────
    if not project_id:
        return ui.Empty(
            message="Select a project in the sidebar, or create one.",
            icon="Folder",
        )

    try:
        pid = int(project_id)
    except ValueError:
        return ui.Empty(message=f"Invalid project_id: {project_id}", icon="AlertCircle")

    # ── Bucket management forms ───────────────────────────────────────
    if mode == "new_bucket":
        return _render_new_bucket_form(pid)
    if mode == "edit_bucket":
        return _render_edit_bucket_form(pid, bucket_id, kwargs.get("bucket_title", ""))
    if mode == "confirm_delete_bucket":
        return _render_confirm_delete_bucket(pid, bucket_id, kwargs.get("bucket_title", ""))

    return await _render_project_board(ctx, imperal_id, pid)


async def _render_smart_view(ctx, imperal_id: str, view: str) -> Any:
    """Single-column tasks list for today / upcoming / overdue smart views."""
    filters = {
        "today": "done = false && due_date >= now/d && due_date < now/d+1d",
        "upcoming": "done = false && due_date >= now && due_date < now+7d",
        "overdue": "done = false && due_date < now && due_date > 1970-01-01",
    }
    titles = {"today": "Today", "upcoming": "Upcoming (7 days)", "overdue": "Overdue"}

    resp = await api_get(ctx, "/v1/tasks/all", {
        "imperal_id": imperal_id,
        "filter": filters[view],
        "sort_by": "due_date" if view != "overdue" else "-priority",
        "per_page": 100,
    })
    if isinstance(resp, dict) and is_no_connection_error(resp):
        return ui.Empty(
            message="Connect your Vikunja in the sidebar to see tasks.",
            icon="Plug",
        )
    tasks = resp if isinstance(resp, list) else []

    if not tasks:
        return ui.Stack([
            _header(titles[view], imperal_id),
            ui.Empty(message="No tasks match this view.", icon="CheckCircle"),
        ], gap=2)

    child_ids = _collect_child_task_ids(tasks)
    top, children = _split_top_and_children(tasks, child_ids)

    body_children: list[Any] = []
    if top:
        body_children.append(ui.Stack(children=[_task_card(t) for t in top], gap=1))
    if children:
        body_children.append(_subtasks_section(children))

    return ui.Stack([
        _header(titles[view], imperal_id, count=len(top)),
        ui.Card(
            title=f"{titles[view]} ({len(top)})",
            content=ui.Stack(children=body_children, gap=1) if body_children
                    else ui.Text("—", variant="caption"),
        ),
    ], gap=2)


async def _render_project_board(ctx, imperal_id: str, project_id: int) -> Any:
    """Kanban board for a specific project."""
    # Fetch project meta
    project = await api_get(ctx, f"/v1/projects/{project_id}", {"imperal_id": imperal_id})
    if isinstance(project, dict) and project.get("status") == "error":
        if is_no_connection_error(project):
            return ui.Empty(
                message="Connect your Vikunja in the sidebar to see this project.",
                icon="Plug",
            )
        return ui.Empty(message=f"Project not found: {project.get('detail')}", icon="AlertCircle")

    proj_title = project.get("title", f"Project #{project_id}")

    # Locate Kanban view
    kanban = await _find_kanban_view(ctx, imperal_id, project_id)
    if kanban is None:
        return ui.Empty(
            message=f"No Kanban view for '{proj_title}' — strange, should be auto-created.",
            icon="AlertCircle",
        )
    view_id = kanban["id"]

    # Fetch buckets WITH embedded tasks. Vikunja v0.21+ splits this:
    # /views/{vid}/buckets returns columns only (tasks=null), while
    # /views/{vid}/tasks returns the same columns with tasks populated.
    buckets = await api_get(
        ctx,
        f"/v1/projects/{project_id}/views/{view_id}/tasks",
        {"imperal_id": imperal_id},
    )
    if not isinstance(buckets, list):
        buckets = []

    # Collect child task ids globally (a subtask may sit in a different bucket
    # than its parent — Vikunja allows that). We hide every child from the
    # main card list and surface them inside a collapsible "↳ Subtasks" section
    # at the bottom of whichever bucket physically holds them.
    all_tasks = [t for b in buckets for t in (b.get("tasks") or [])]
    child_ids = _collect_child_task_ids(all_tasks)

    columns = []
    for b in buckets:
        btitle = b.get("title", "?")
        bid = b.get("id")
        tasks = b.get("tasks") or []
        top, children = _split_top_and_children(tasks, child_ids)

        action_row = ui.Stack([
            ui.Button(
                "✎",
                size="sm",
                variant="ghost",
                on_click=ui.Call(
                    "__panel__editor",
                    note_id="bucket_manage",
                    project_id=str(project_id),
                    mode="edit_bucket",
                    bucket_id=str(bid),
                    bucket_title=btitle,
                ),
            ),
            ui.Button(
                "✕",
                size="sm",
                variant="ghost",
                on_click=ui.Call(
                    "__panel__editor",
                    note_id="bucket_manage",
                    project_id=str(project_id),
                    mode="confirm_delete_bucket",
                    bucket_id=str(bid),
                    bucket_title=btitle,
                ),
            ),
            ui.Button(
                "+ Task",
                icon="Plus",
                size="sm",
                variant="ghost",
                on_click=ui.Call(
                    "__panel__editor",
                    note_id="new",
                    mode="new",
                    project_id=str(project_id),
                    bucket_id=str(bid),
                ),
            ),
        ], direction="h", gap=1, wrap=True)

        bucket_body: list[Any] = [action_row]
        if top:
            bucket_body.append(ui.List(items=[_task_card(t) for t in top]))
        elif not children:
            bucket_body.append(ui.Text("—", variant="caption"))
        if children:
            bucket_body.append(_subtasks_section(children))

        columns.append(
            ui.Card(
                title=f"{btitle} ({len(top)})",
                content=ui.Stack(children=bucket_body, gap=1),
            )
        )

    if not columns:
        body = ui.Empty(
            message="No buckets yet. Vikunja creates them automatically — check project config.",
            icon="Columns",
        )
    else:
        body = ui.Stack(children=columns, direction="h", gap=2, wrap=False, className="overflow-x-auto")

    return ui.Stack([
        _header(proj_title, imperal_id, project_id=project_id),
        body,
    ], gap=2)


# ─── Header action bar ─────────────────────────────────────────────────── #

def _header(title: str, imperal_id: str, project_id: int | None = None, count: int | None = None) -> Any:
    label = title if count is None else f"{title} ({count})"

    actions = []
    if project_id is not None:
        actions.append(
            ui.Button(
                "+ Task",
                icon="Plus",
                variant="primary",
                size="sm",
                on_click=ui.Call("__panel__editor", note_id="new", mode="new", project_id=str(project_id)),
            )
        )
        actions.append(
            ui.Button(
                "+ Column",
                icon="Columns",
                variant="ghost",
                size="sm",
                on_click=ui.Call(
                    "__panel__editor",
                    note_id="bucket_manage",
                    project_id=str(project_id),
                    mode="new_bucket",
                ),
            )
        )
    actions.append(
        ui.Button(
            "Back",
            icon="ArrowLeft",
            variant="ghost",
            size="sm",
            on_click=ui.Call("__panel__editor", note_id="board"),
        )
    )

    return ui.Stack([
        ui.Text(label, variant="h3"),
        ui.Stack(actions, direction="h", gap=1, wrap=True),
    ], direction="h", sticky=True)


# ─── Bucket management forms ───────────────────────────────────────────── #

def _bucket_form_header(title: str, project_id: int) -> Any:
    return ui.Stack([
        ui.Text(title, variant="h3"),
        ui.Button(
            "Cancel",
            icon="ArrowLeft",
            variant="ghost",
            size="sm",
            on_click=ui.Call(
                "__panel__editor",
                note_id=str(project_id),
                project_id=str(project_id),
            ),
        ),
    ], direction="h", sticky=True)


def _render_new_bucket_form(project_id: int) -> Any:
    return ui.Stack([
        _bucket_form_header("New Column", project_id),
        ui.Card(
            title="Create Column",
            content=ui.Form(
                action="create_bucket",
                submit_label="Create",
                defaults={"project_id": project_id},
                children=[
                    ui.Input(placeholder="Column name", param_name="title"),
                    ui.Input(
                        placeholder="WIP limit — max tasks (0 or empty = no limit)",
                        param_name="limit",
                    ),
                ],
            ),
        ),
    ], gap=2)


def _render_edit_bucket_form(project_id: int, bucket_id: str, bucket_title: str) -> Any:
    try:
        bid = int(bucket_id)
    except (ValueError, TypeError):
        return ui.Empty(message="Invalid bucket ID.", icon="AlertCircle")
    return ui.Stack([
        _bucket_form_header(f"Rename Column", project_id),
        ui.Card(
            title=f"Rename \"{bucket_title}\"",
            content=ui.Form(
                action="rename_bucket",
                submit_label="Rename",
                defaults={"project_id": project_id, "bucket_id": bid, "title": bucket_title},
                children=[
                    ui.Input(placeholder="New column name", param_name="title"),
                    ui.Input(
                        placeholder="WIP limit — max tasks (0 or empty = no limit)",
                        param_name="limit",
                    ),
                ],
            ),
        ),
    ], gap=2)


def _render_confirm_delete_bucket(project_id: int, bucket_id: str, bucket_title: str) -> Any:
    try:
        bid = int(bucket_id)
    except (ValueError, TypeError):
        return ui.Empty(message="Invalid bucket ID.", icon="AlertCircle")
    return ui.Stack([
        _bucket_form_header("Delete Column", project_id),
        ui.Card(
            title=f"Delete \"{bucket_title}\"?",
            content=ui.Form(
                action="delete_bucket",
                submit_label="Yes, delete column",
                defaults={"project_id": project_id, "bucket_id": bid},
                children=[
                    ui.Text(
                        f"Tasks in \"{bucket_title}\" will be moved to the default column. "
                        "This cannot be undone.",
                        variant="caption",
                    ),
                ],
            ),
        ),
    ], gap=2)
