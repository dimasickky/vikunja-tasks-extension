"""tasks · Skeleton tools — background refresh + alert."""
from __future__ import annotations

import logging

from app import ext, api_get, _imperal_id, is_no_connection_error

log = logging.getLogger("tasks.skeleton")


@ext.skeleton(
    "tasks",
    alert=True,
    ttl=300,
    description="Background: today/overdue/upcoming counts + recent tasks + active projects.",
)
async def skeleton_refresh_tasks(ctx) -> dict:
    """Refresh task counters and recent activity. Idempotent — safe per tick."""
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return {"response": {"note": "no user on context"}}

    conn = await api_get(ctx, "/v1/connection", {"imperal_id": imperal_id}) or {}
    if not conn.get("connected") or conn.get("status") == "error":
        return {"response": {
            "connected": False,
            "today_count": 0,
            "overdue_count": 0,
            "upcoming_7d_count": 0,
            "active_projects_count": 0,
            "active_projects": [],
            "favorite_projects": [],
            "recent_tasks": [],
        }}

    async def _count_filter(flt: str) -> int:
        resp = await api_get(ctx, "/v1/tasks/all", {
            "imperal_id": imperal_id, "filter": flt, "per_page": 200,
        })
        if isinstance(resp, dict) and is_no_connection_error(resp):
            return 0
        return len(resp) if isinstance(resp, list) else 0

    try:
        today_count = await _count_filter(
            "done = false && due_date >= now/d && due_date < now/d+1d"
        )
        overdue_count = await _count_filter(
            "done = false && due_date < now && due_date > 1970-01-01"
        )
        upcoming_7d_count = await _count_filter(
            "done = false && due_date >= now && due_date < now+7d"
        )

        recent_raw = await api_get(ctx, "/v1/tasks/all", {
            "imperal_id": imperal_id, "sort_by": "-updated", "per_page": 5,
        })
        recent = recent_raw if isinstance(recent_raw, list) else []
        recent_tasks = [
            {
                "task_id":    t.get("id"),
                "title":      t.get("title", "")[:80],
                "done":       t.get("done", False),
                "due_date":   (t.get("due_date") or "")[:10],
                "project_id": t.get("project_id"),
            }
            for t in recent
        ]

        projects_raw = await api_get(ctx, "/v1/projects", {"imperal_id": imperal_id})
        projects = projects_raw if isinstance(projects_raw, list) else []
        active_projects = [p for p in projects if not p.get("is_archived", False)]
        favorites = [p for p in active_projects if p.get("is_favorite", False)]

        return {"response": {
            "connected":              True,
            "today_count":            today_count,
            "overdue_count":          overdue_count,
            "upcoming_7d_count":      upcoming_7d_count,
            "active_projects_count":  len(active_projects),
            "active_projects": [
                {"project_id": p["id"], "title": p.get("title", "")}
                for p in active_projects[:20]
            ],
            "favorite_projects": [
                {"project_id": p["id"], "title": p.get("title", "")}
                for p in favorites[:5]
            ],
            "recent_tasks": recent_tasks,
        }}
    except Exception as e:
        log.error("skeleton_refresh_tasks failed: %s", e)
        return {"response": {"error": str(e)}}


@ext.tool(
    "skeleton_alert_tasks",
    scopes=["tasks.read"],
    description="Alerts: overdue tasks, due-today, sudden spike in backlog.",
)
async def skeleton_alert_tasks(ctx, old: dict = None, new: dict = None, **kwargs) -> dict:
    """Compare old/new skeleton, alert on overdue spikes and due-today changes."""
    if not new:
        return {"response": ""}

    alerts: list[str] = []
    overdue = new.get("overdue_count", 0)
    today = new.get("today_count", 0)
    old_overdue = (old or {}).get("overdue_count", 0)

    if overdue > 0 and overdue > old_overdue:
        delta = overdue - old_overdue
        if delta == overdue:
            alerts.append(f"⚠ {overdue} task{'s' if overdue > 1 else ''} overdue")
        else:
            alerts.append(f"⚠ {delta} new overdue task{'s' if delta > 1 else ''} (now {overdue} total)")

    if today > 0 and today != (old or {}).get("today_count", 0):
        alerts.append(f"📅 {today} task{'s' if today > 1 else ''} due today")

    if not alerts:
        return {"response": ""}

    return {"response": " · ".join(alerts)}
