"""tasks · Sidebar panel (slot=left) — smart views + projects tree.

Users stay inside Imperal Panel — no external redirects to tasks.webhostmost.com.
All navigation → center panels (board / task detail) via ui.Call.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext, api_get, _imperal_id

log = logging.getLogger("tasks.panels")


# ─── Sidebar ───────────────────────────────────────────────────────────── #

@ext.panel(
    "sidebar",
    slot="left",
    title="Tasks",
    icon="Kanban",
    default_width=260,
    min_width=220,
    max_width=400,
    refresh=(
        "on_event:task.created,task.updated,task.completed,task.deleted,"
        "project.created,project.updated,project.archived,project.deleted"
    ),
)
async def tasks_sidebar(ctx, view: str = "main", active_project_id: str = "", **kwargs):
    """Sidebar: smart views + projects tree. Open any → center kanban board."""
    imperal_id = _imperal_id(ctx)
    children: list = []

    # ── Top action bar ────────────────────────────────────────────────
    children.append(ui.Stack([
        ui.Button(
            "New Task",
            icon="Plus",
            variant="primary",
            size="sm",
            on_click=ui.Call("__panel__task", mode="new"),
        ),
        ui.Button(
            "New Project",
            icon="FolderPlus",
            variant="ghost",
            size="sm",
            on_click=ui.Call("__panel__sidebar", view="new_project"),
        ),
    ], direction="horizontal", wrap=True, sticky=True))

    # ── Inline "new project" form ─────────────────────────────────────
    if view == "new_project":
        children.append(ui.Card(
            title="New Project",
            content=ui.Stack([
                ui.Input(placeholder="Project title", param_name="title"),
                ui.Input(placeholder="Description (optional)", param_name="description"),
                ui.Input(placeholder="Color (hex, e.g. ff5500)", param_name="hex_color"),
                ui.Stack([
                    ui.Button(
                        "Create",
                        icon="Check",
                        variant="primary",
                        size="sm",
                        on_click=ui.Call("create_project"),
                    ),
                    ui.Button(
                        "Cancel",
                        variant="ghost",
                        size="sm",
                        on_click=ui.Call("__panel__sidebar", view="main"),
                    ),
                ], direction="horizontal", gap=1),
            ], gap=2),
        ))

    # ── Smart views ───────────────────────────────────────────────────
    # TODO: counters from skeleton (refresh_tasks). MVP: labels only.
    smart_items = [
        ui.ListItem(
            title="Today",
            icon="Calendar",
            on_click=ui.Call("__panel__board", view="today"),
        ),
        ui.ListItem(
            title="Upcoming (7d)",
            icon="CalendarDays",
            on_click=ui.Call("__panel__board", view="upcoming"),
        ),
        ui.ListItem(
            title="Overdue",
            icon="AlertCircle",
            on_click=ui.Call("__panel__board", view="overdue"),
        ),
    ]
    children.append(ui.Card(title="Smart views", content=ui.List(items=smart_items)))

    # ── Projects list ─────────────────────────────────────────────────
    if not imperal_id:
        children.append(ui.Empty(message="Not provisioned yet", icon="UserX"))
        return ui.Stack(children=children, gap=2)

    projects = []
    try:
        resp = await api_get("/v1/projects", {"imperal_id": imperal_id})
        if isinstance(resp, list):
            projects = resp
        elif isinstance(resp, dict) and resp.get("status") == "error":
            log.warning("failed to fetch projects: %s", resp.get("detail"))
    except Exception as e:
        log.exception("fetch projects error: %s", e)

    # Filter out archived unless view=archived
    active_projects = [p for p in projects if not p.get("is_archived", False)]

    if not active_projects:
        children.append(ui.Card(
            title="Projects",
            content=ui.Empty(
                message="No projects yet — create your first one above.",
                icon="Folder",
            ),
        ))
        return ui.Stack(children=children, gap=2)

    project_items = []
    for p in active_projects:
        pid = p["id"]
        title = p.get("title", f"#{pid}")
        is_active = str(pid) == active_project_id
        project_items.append(
            ui.ListItem(
                title=title,
                icon="Folder",
                selected=is_active,
                on_click=ui.Call("__panel__board", project_id=str(pid)),
            )
        )

    children.append(ui.Card(
        title="Projects",
        content=ui.List(items=project_items),
    ))

    return ui.Stack(children=children, gap=2)
