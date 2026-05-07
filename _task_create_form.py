"""tasks · Task create form renderer (split from panels_task.py)."""
from __future__ import annotations

from typing import Any

from imperal_sdk import ui

from app import api_get, imperal_id_of


def _priority_options() -> list:
    return [
        {"value": "0", "label": "0 — none"},
        {"value": "1", "label": "1 — low"},
        {"value": "2", "label": "2 — medium"},
        {"value": "3", "label": "3 — high"},
        {"value": "4", "label": "4 — urgent"},
        {"value": "5", "label": "5 — critical"},
    ]


def _header_bar(title: str, actions: list | None = None) -> Any:
    row = [ui.Text(title, variant="h3")]
    if actions:
        row.append(ui.Stack(actions, direction="h", gap=1))
    return ui.Stack(row, direction="h", sticky=True)


async def render_create_form(ctx, project_id: str) -> Any:
    imperal_id = imperal_id_of(ctx)

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
    bucket_options: list = []
    views_resp = await api_get(ctx, f"/v1/projects/{pid}/views", {"imperal_id": imperal_id})
    if isinstance(views_resp, list):
        kanban = next((v for v in views_resp if v.get("view_kind") == "kanban"), None)
        if kanban:
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
        form_children.append(ui.Select(param_name="bucket_id", options=bucket_options))

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
                    on_click=ui.Call("__panel__editor", note_id="board", project_id=project_id),
                ),
            ], gap=2),
        ),
    ], gap=2)
