"""tasks · Skeleton tools — background refresh + alert.

Kernel calls these on TTL to keep sidebar counters fresh and provide
Webbee with context ("you have 3 tasks due today, 1 overdue").
"""
from __future__ import annotations

import logging

from app import ext, api_get, _imperal_id

log = logging.getLogger("tasks.skeleton")


# ─── Refresh ──────────────────────────────────────────────────────────── #

@ext.tool(
    "skeleton_refresh_tasks",
    scopes=["tasks.read"],
    description="Background: today/overdue/upcoming counts + recent tasks + active projects.",
)
async def skeleton_refresh_tasks(ctx, **kwargs) -> dict:
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return {"response": {"note": "not provisioned"}}

    async def _count_filter(flt: str) -> int:
        resp = await api_get("/v1/tasks/all", {
            "imperal_id": imperal_id,
            "filter": flt,
            "per_page": 200,
        })
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

        # Recent tasks (5 most recently updated, any status)
        recent_raw = await api_get("/v1/tasks/all", {
            "imperal_id": imperal_id,
            "sort_by": "-updated",
            "per_page": 5,
        })
        recent = recent_raw if isinstance(recent_raw, list) else []
        recent_tasks = [
            {
                "task_id": t.get("id"),
                "title": t.get("title", "")[:80],
                "done": t.get("done", False),
                "due_date": (t.get("due_date") or "")[:10],
                "project_id": t.get("project_id"),
            }
            for t in recent
        ]

        # Active projects
        projects_raw = await api_get("/v1/projects", {"imperal_id": imperal_id})
        projects = projects_raw if isinstance(projects_raw, list) else []
        active_projects = [p for p in projects if not p.get("is_archived", False)]
        favorites = [p for p in active_projects if p.get("is_favorite", False)]

        return {"response": {
            "today_count": today_count,
            "overdue_count": overdue_count,
            "upcoming_7d_count": upcoming_7d_count,
            "active_projects_count": len(active_projects),
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


# ─── Alert ────────────────────────────────────────────────────────────── #

@ext.tool(
    "skeleton_alert_tasks",
    scopes=["tasks.read"],
    description="Alerts: overdue tasks, due-today, sudden spike in backlog.",
)
async def skeleton_alert_tasks(ctx, old: dict = None, new: dict = None, **kwargs) -> dict:
    if not new:
        return {"response": ""}

    alerts: list[str] = []

    overdue = new.get("overdue_count", 0)
    today = new.get("today_count", 0)
    old_overdue = (old or {}).get("overdue_count", 0)

    if overdue > 0 and overdue > old_overdue:
        delta = overdue - old_overdue
        if delta == overdue:
            alerts.append(
                f"⚠ {overdue} task{'s' if overdue > 1 else ''} overdue"
            )
        else:
            alerts.append(
                f"⚠ {delta} new overdue task{'s' if delta > 1 else ''} (now {overdue} total)"
            )

    if today > 0 and today != (old or {}).get("today_count", 0):
        alerts.append(
            f"📅 {today} task{'s' if today > 1 else ''} due today"
        )

    if not alerts:
        return {"response": ""}

    return {"response": " · ".join(alerts)}
