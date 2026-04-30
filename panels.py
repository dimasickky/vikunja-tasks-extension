"""tasks · Sidebar panel — connect-first UX (v2.0.0 BYO).

States:
  0. not connected → connect form + help link  (default for new users)
  1. validating    → spinner during connect submission
  2. error         → friendly English message + retry
  3. connected     → smart views + projects tree + footer with disconnect
  4. broken        → "connection lost" banner + reconnect form

Connection state is the SINGLE source of truth. We never fall back to a
shared instance, never invent placeholder content. Tool calls (chat or
panel ui.Call) that require a connection get a 412 from the bridge,
which handlers translate into a clear "Connect your Vikunja first" reply.
"""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import ext, api_get, _imperal_id, is_no_connection_error

log = logging.getLogger("tasks.panels")


# ─── Sidebar ───────────────────────────────────────────────────────────── #

@ext.panel(
    "sidebar",
    slot="left",
    title="Tasks",
    icon="Kanban",
    default_width=280,
    min_width=240,
    max_width=420,
    refresh=(
        "on_event:connection.created,connection.deleted,"
        "task.created,task.updated,task.completed,task.deleted,"
        "project.created,project.updated,project.archived,project.deleted"
    ),
)
async def tasks_sidebar(ctx, view: str = "main", active_project_id: str = "", **kwargs):
    """Sidebar: connect form when disconnected; smart views + projects when connected."""
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return ui.Empty(message="Sign in to use tasks.", icon="UserX")

    # Probe connection status via bridge.
    conn = await api_get("/v1/connection", {"imperal_id": imperal_id}) or {}
    connected = bool(conn.get("connected")) and conn.get("status") != "error"

    if not connected:
        return _render_connect(view)

    # ── Connected state ───────────────────────────────────────────────
    children: list = [_top_actions(view)]

    if view == "new_project":
        children.append(_inline_new_project_form())

    children.append(_smart_views_card())

    # Projects list
    projects_resp = await api_get("/v1/projects", {"imperal_id": imperal_id})
    if isinstance(projects_resp, dict) and projects_resp.get("status") == "error":
        if is_no_connection_error(projects_resp):
            # Connection died between status check and projects fetch — render reconnect.
            return _render_connect(view, banner="Connection to Vikunja was lost — please reconnect.")
        children.append(ui.Card(
            title="Projects",
            content=ui.Empty(
                message="Couldn't load projects. Try refreshing the page.",
                icon="AlertTriangle",
            ),
        ))
        children.append(_footer(conn))
        return ui.Stack(children=children, gap=2)

    projects = projects_resp if isinstance(projects_resp, list) else []
    children.append(_projects_card(projects, active_project_id))
    children.append(_footer(conn))

    root = ui.Stack(children=children, gap=2)

    # Claim the center slot on first load (same as notes auto_action pattern).
    # Without this, the first ui.Call("__panel__editor") from a sidebar click
    # opens in the chat/right area instead of the center column.
    if not active_project_id:
        root.props["auto_action"] = ui.Call("__panel__editor")

    return root


# ─── Connect-form view ─────────────────────────────────────────────────── #

def _render_connect(view: str, banner: str | None = None) -> ui.Stack:
    """Empty/connect/error states fall through this single rendering path."""
    children: list = []

    if banner:
        children.append(ui.Card(
            title="Reconnect required",
            content=ui.Text(banner, variant="caption"),
        ))

    use_pat = view == "connect_pat"

    children.append(ui.Card(
        title="Connect your Vikunja",
        content=ui.Stack([
            ui.Text(
                "Sign in to your own Vikunja instance to manage tasks here. "
                "Your password is exchanged once for an API token, which is "
                "encrypted at rest. Disconnect any time — the token is revoked.",
                variant="caption",
            ),
            ui.Form(
                action="connect_vikunja_with_pat" if use_pat else "connect_vikunja",
                submit_label="Connect with token" if use_pat else "Connect",
                children=[
                    ui.Input(
                        placeholder="https://vikunja.your-domain.com",
                        param_name="base_url",
                    ),
                    *(
                        [ui.Input(
                            placeholder="API token (from Settings → API tokens)",
                            param_name="pat",
                        )]
                        if use_pat else
                        [
                            ui.Input(placeholder="Username", param_name="username"),
                            ui.Input(placeholder="Password", param_name="password"),
                        ]
                    ),
                ],
            ),
            ui.Button(
                "I have a token" if not use_pat else "Use username + password",
                icon="Key" if not use_pat else "User",
                variant="ghost",
                size="sm",
                on_click=ui.Call(
                    "__panel__sidebar",
                    view="connect_pat" if not use_pat else "main",
                ),
            ),
        ], gap=2),
    ))

    children.append(ui.Card(
        title="No Vikunja yet?",
        content=ui.Stack([
            ui.Text(
                "Vikunja is a self-hostable, open-source task tracker. "
                "Spin it up in 5 minutes with Docker Compose, or use the "
                "hosted plan if you'd rather skip self-hosting.",
                variant="caption",
            ),
            ui.Stack([
                ui.Button(
                    "Self-host (vikunja.io)",
                    icon="ExternalLink",
                    variant="ghost",
                    size="sm",
                    on_click=ui.Call("__panel__sidebar"),
                ),
                ui.Button(
                    "Hosted (try.vikunja.io)",
                    icon="ExternalLink",
                    variant="ghost",
                    size="sm",
                    on_click=ui.Call("__panel__sidebar"),
                ),
            ], direction="h", gap=2, wrap=True),
        ], gap=2),
    ))

    return ui.Stack(children=children, gap=2, className="min-h-full")


# ─── Connected-state pieces ────────────────────────────────────────────── #

def _top_actions(view: str) -> ui.Stack:
    new_project_active = view == "new_project"
    return ui.Stack([
        ui.Button(
            "New Task",
            icon="Plus",
            variant="primary",
            size="sm",
            on_click=ui.Call("__panel__editor", mode="new"),
        ),
        ui.Button(
            "New Project",
            icon="FolderPlus",
            variant="secondary" if new_project_active else "ghost",
            size="sm",
            on_click=ui.Call(
                "__panel__sidebar",
                view="main" if new_project_active else "new_project",
            ),
        ),
    ], direction="h", wrap=True, sticky=True)


def _inline_new_project_form() -> ui.Card:
    return ui.Card(
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
            ], direction="h", gap=1),
        ], gap=2),
    )


def _smart_views_card() -> ui.Card:
    items = [
        ui.ListItem(
            id="smart_today",
            title="Today",
            icon="Calendar",
            on_click=ui.Call("__panel__editor", view="today"),
        ),
        ui.ListItem(
            id="smart_upcoming",
            title="Upcoming (7d)",
            icon="CalendarDays",
            on_click=ui.Call("__panel__editor", view="upcoming"),
        ),
        ui.ListItem(
            id="smart_overdue",
            title="Overdue",
            icon="AlertCircle",
            on_click=ui.Call("__panel__editor", view="overdue"),
        ),
    ]
    return ui.Card(title="Smart views", content=ui.List(items=items))


def _projects_card(projects: list, active_project_id: str) -> ui.Card:
    active = [p for p in projects if not p.get("is_archived", False)]
    if not active:
        return ui.Card(
            title="Projects",
            content=ui.Empty(
                message="No projects yet — create your first one above.",
                icon="Folder",
            ),
        )
    items = []
    for p in active:
        pid = p["id"]
        title = p.get("title", f"#{pid}")
        items.append(ui.ListItem(
            id=f"project_{pid}",
            title=title,
            icon="Folder",
            selected=str(pid) == active_project_id,
            on_click=ui.Call("__panel__editor", project_id=str(pid)),
        ))
    return ui.Card(title="Projects", content=ui.List(items=items))


def _footer(conn: dict) -> ui.Stack:
    base = conn.get("base_url") or "?"
    user = conn.get("username") or "?"
    return ui.Stack([
        ui.Text(f"Connected to {base} as {user}", variant="caption"),
        ui.Button(
            "Disconnect",
            icon="LogOut",
            variant="ghost",
            size="sm",
            on_click=ui.Call("disconnect_vikunja"),
        ),
    ], direction="h", gap=2, sticky=True)
