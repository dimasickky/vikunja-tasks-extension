"""tasks · Skeleton refresh + alert.

Refresh uses the v1.6 convention-based ``@ext.skeleton`` decorator — the
kernel auto-derives the section name (``tasks``) + TTL (300s) from the
decorator args and surfaces scalar counters directly in the classifier
envelope so the Narrator sees "you have 3 tasks due today, 1 overdue"
without an extra fetch.

Alert is a companion tool (``skeleton_alert_tasks``) the kernel invokes
with ``old`` / ``new`` snapshots after every refresh — returning a short
human string appears in the user's alert bar when it changes.
"""
from __future__ import annotations

import logging

from app import api_get, ext

log = logging.getLogger("tasks.skeleton")


# ─── Refresh ─────────────────────────────────────────────────────────── #

@ext.skeleton(
    "tasks",
    alert=True,
    ttl=300,
    description=(
        "Today / overdue / upcoming-7d counts plus active projects and "
        "five most-recent tasks — feeds the sidebar counters and classifier."
    ),
)
async def skeleton_refresh_tasks(ctx, **kwargs) -> dict:
    imperal_id = ctx.user.id if hasattr(ctx, "user") and ctx.user else ""
    if not imperal_id:
        return {"response": {"note": "not provisioned"}}

    async def _count_filter(flt: str) -> int:
        resp = await api_get("/v1/tasks/all", {
            "imperal_id": imperal_id, "filter": flt, "per_page": 200,
        })
        return len(resp) if isinstance(resp, list) else 0

    try:
        today_count = await _count_filter(
            "done = false && due_date >= now/d && due_date < now/d+1d",
        )
        overdue_count = await _count_filter(
            "done = false && due_date < now && due_date > 1970-01-01",
        )
        upcoming_7d_count = await _count_filter(
            "done = false && due_date >= now && due_date < now+7d",
        )

        recent_raw = await api_get("/v1/tasks/all", {
            "imperal_id": imperal_id, "sort_by": "-updated", "per_page": 5,
        })
        recent = recent_raw if isinstance(recent_raw, list) else []

        projects_raw = await api_get("/v1/projects", {"imperal_id": imperal_id})
        projects = projects_raw if isinstance(projects_raw, list) else []
        active_projects = [p for p in projects if not p.get("is_archived", False)]
        favorites = [p for p in active_projects if p.get("is_favorite", False)]

        return {"response": {
            "today_count":           today_count,
            "overdue_count":         overdue_count,
            "upcoming_7d_count":     upcoming_7d_count,
            "active_projects_count": len(active_projects),
            "active_projects": [
                {"project_id": p["id"], "title": p.get("title", "")}
                for p in active_projects[:20]
            ],
            "favorite_projects": [
                {"project_id": p["id"], "title": p.get("title", "")}
                for p in favorites[:5]
            ],
            "recent_tasks": [
                {
                    "task_id":    t.get("id"),
                    "title":      (t.get("title") or "")[:80],
                    "done":       t.get("done", False),
                    "due_date":   (t.get("due_date") or "")[:10],
                    "project_id": t.get("project_id"),
                } for t in recent
            ],
        }}
    except Exception as e:
        log.error("skeleton_refresh_tasks failed: %s", e)
        return {"response": {"error": str(e)}}


# ─── Alert ───────────────────────────────────────────────────────────── #
#
# The ``alert=True`` flag on @ext.skeleton tells the platform to look for a
# companion tool named ``skeleton_alert_<section>`` and call it on change.
# Declaring it as a raw ``@ext.tool`` is the canonical pattern — skeleton()
# only wires the refresh tool, never the alert.

@ext.tool(
    "skeleton_alert_tasks",
    scopes=[],
    description="Alerts: overdue tasks, due-today, backlog spikes.",
)
async def skeleton_alert_tasks(
    ctx, old: dict | None = None, new: dict | None = None, **kwargs,
) -> dict:
    if not new:
        return {"response": ""}

    alerts: list[str] = []
    overdue     = new.get("overdue_count", 0)
    today       = new.get("today_count",   0)
    old_overdue = (old or {}).get("overdue_count", 0)
    old_today   = (old or {}).get("today_count",   0)

    if overdue > 0 and overdue > old_overdue:
        delta = overdue - old_overdue
        if delta == overdue:
            alerts.append(f"⚠ {overdue} task{'s' if overdue > 1 else ''} overdue")
        else:
            alerts.append(
                f"⚠ {delta} new overdue task{'s' if delta > 1 else ''} "
                f"(now {overdue} total)",
            )

    if today > 0 and today != old_today:
        alerts.append(f"📅 {today} task{'s' if today > 1 else ''} due today")

    return {"response": " · ".join(alerts) if alerts else ""}
