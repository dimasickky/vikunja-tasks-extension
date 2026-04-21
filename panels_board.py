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

from app import ext, api_get, _imperal_id

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


def _task_card(task: dict) -> Any:
    title = task.get("title", "?")
    tid = task["id"]
    prio = task.get("priority", 0)
    due = _due_badge(task)
    done = task.get("done", False)

    meta_parts = []
    if due:
        meta_parts.append(f"📅 {due}")
    if prio >= 3:
        meta_parts.append(f"⚠ {_priority_label(prio)}")
    meta = " · ".join(meta_parts) if meta_parts else None

    return ui.Card(
        title=f"{'✅ ' if done else ''}{title}",
        content=ui.Text(meta or "", variant="caption") if meta else None,
        on_click=ui.Call("__panel__task", task_id=str(tid)),
    )


async def _find_kanban_view(imperal_id: str, project_id: int) -> dict | None:
    """Locate the Kanban view of a project. Vikunja auto-creates one per project."""
    views = await api_get(f"/v1/projects/{project_id}/views", {"imperal_id": imperal_id})
    if not isinstance(views, list):
        return None
    for v in views:
        if v.get("view_kind") == "kanban":
            return v
    return None


# ─── Panel ─────────────────────────────────────────────────────────────── #

@ext.panel(
    "board",
    slot="center",
    title="Board",
    icon="Kanban",
    refresh=(
        "on_event:task.created,task.updated,task.completed,task.deleted,"
        "task.moved,task.bucket_changed,task.due_changed,task.priority_changed,"
        "project.created,project.updated"
    ),
)
async def tasks_board(
    ctx,
    project_id: str = "",
    view: str = "",
    **kwargs,
):
    """Kanban board for a project, or filtered smart view across all projects."""
    imperal_id = _imperal_id(ctx)

    if not imperal_id:
        return ui.Empty(message="Not provisioned yet", icon="UserX")

    # ── Smart views (no project_id) ───────────────────────────────────
    if view in ("today", "upcoming", "overdue"):
        return await _render_smart_view(imperal_id, view)

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

    return await _render_project_board(imperal_id, pid)


async def _render_smart_view(imperal_id: str, view: str) -> Any:
    """Single-column tasks list for today / upcoming / overdue smart views."""
    filters = {
        "today": "done = false && due_date >= now/d && due_date < now/d+1d",
        "upcoming": "done = false && due_date >= now && due_date < now+7d",
        "overdue": "done = false && due_date < now && due_date > 1970-01-01",
    }
    titles = {"today": "Today", "upcoming": "Upcoming (7 days)", "overdue": "Overdue"}

    resp = await api_get("/v1/tasks/all", {
        "imperal_id": imperal_id,
        "filter": filters[view],
        "sort_by": "due_date" if view != "overdue" else "-priority",
        "per_page": 100,
    })
    tasks = resp if isinstance(resp, list) else []

    if not tasks:
        return ui.Stack([
            _header(titles[view], imperal_id),
            ui.Empty(message="No tasks match this view.", icon="CheckCircle"),
        ], gap=2)

    cards = [_task_card(t) for t in tasks]
    return ui.Stack([
        _header(titles[view], imperal_id, count=len(tasks)),
        ui.Card(
            title=f"{titles[view]} ({len(tasks)})",
            content=ui.List(children=cards),
        ),
    ], gap=2)


async def _render_project_board(imperal_id: str, project_id: int) -> Any:
    """Kanban board for a specific project."""
    # Fetch project meta
    project = await api_get(f"/v1/projects/{project_id}", {"imperal_id": imperal_id})
    if isinstance(project, dict) and project.get("status") == "error":
        return ui.Empty(message=f"Project not found: {project.get('detail')}", icon="AlertCircle")

    proj_title = project.get("title", f"Project #{project_id}")

    # Locate Kanban view
    kanban = await _find_kanban_view(imperal_id, project_id)
    if kanban is None:
        return ui.Empty(
            message=f"No Kanban view for '{proj_title}' — strange, should be auto-created.",
            icon="AlertCircle",
        )
    view_id = kanban["id"]

    # Fetch buckets (with embedded tasks — Vikunja returns them together)
    buckets = await api_get(
        f"/v1/projects/{project_id}/views/{view_id}/buckets",
        {"imperal_id": imperal_id},
    )
    if not isinstance(buckets, list):
        buckets = []

    # Build column UI
    columns = []
    for b in buckets:
        btitle = b.get("title", "?")
        bid = b.get("id")
        tasks = b.get("tasks") or []
        task_cards = [_task_card(t) for t in tasks]
        columns.append(
            ui.Card(
                title=f"{btitle} ({len(tasks)})",
                content=ui.List(children=task_cards) if task_cards else
                        ui.Text("—", variant="caption"),
            )
        )

    if not columns:
        body = ui.Empty(
            message="No buckets yet. Vikunja creates them automatically — check project config.",
            icon="Columns",
        )
    else:
        body = ui.Stack(children=columns, direction="horizontal", gap=2, wrap=False)

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
                on_click=ui.Call("__panel__task", mode="new", project_id=str(project_id)),
            )
        )
    actions.append(
        ui.Button(
            "Back",
            icon="ArrowLeft",
            variant="ghost",
            size="sm",
            on_click=ui.Call("__panel__board"),
        )
    )

    return ui.Stack([
        ui.Text(label, variant="h3"),
        ui.Stack(actions, direction="horizontal", gap=1),
    ], direction="horizontal", sticky=True)
