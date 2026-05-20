"""tasks · Skeleton tools — background refresh + alert."""
from __future__ import annotations

import asyncio
import logging

from app import ext, api_get, imperal_id_of, is_no_connection_error

log = logging.getLogger("tasks.skeleton")


# NOTE on TTL (v3.2.0): SDK 4.1.0 SkeletonClient is read-only — there is no
# `ctx.skeleton.invalidate()` API for handlers to call after a write. The
# canonical refresh path is the kernel skeleton-tick workflow (per-extension
# `ttl_seconds`). To keep the LLM's view of task counters / recent_tasks fresh
# after writes initiated through chat, we lower TTL from 300s to 30s. Panels
# (panels.py / panels_editor.py / panels_task.py) do NOT read skeleton — they
# fetch fresh via api_get — so panel UX is already real-time via
# `refresh_panels`. The 30s TTL closes the staleness window for the LLM only.
@ext.skeleton(
    "tasks",
    alert=True,
    ttl=30,
    description="Background: today/overdue/upcoming counts + recent tasks + active projects.",
)
async def skeleton_refresh_tasks(ctx) -> dict:
    """Refresh task counters and recent activity. Idempotent — safe per tick."""
    imperal_id = imperal_id_of(ctx)
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
        _KANBAN_VIEW_KINDS = {"kanban", 4}

        _results = await asyncio.gather(
            api_get(ctx, "/v1/tasks/all", {
                "imperal_id": imperal_id,
                "filter": "done = false && due_date >= now/d && due_date < now/d+1d",
                "per_page": 200,
            }),
            api_get(ctx, "/v1/tasks/all", {
                "imperal_id": imperal_id,
                "filter": "done = false && due_date < now && due_date > 1970-01-01",
                "per_page": 200,
            }),
            api_get(ctx, "/v1/tasks/all", {
                "imperal_id": imperal_id,
                "filter": "done = false && due_date >= now && due_date < now+7d",
                "per_page": 200,
            }),
            api_get(ctx, "/v1/tasks/all", {
                "imperal_id": imperal_id, "sort_by": "-updated", "per_page": 5,
            }),
            api_get(ctx, "/v1/projects", {"imperal_id": imperal_id}),
            api_get(ctx, "/v1/users", {"imperal_id": imperal_id, "s": ""}),
            return_exceptions=True,
        )
        today_raw, overdue_raw, upcoming_raw, recent_raw, projects_raw, users_raw = (
            r if not isinstance(r, Exception) else [] for r in _results
        )

        def _count(resp) -> int:
            if isinstance(resp, dict) and is_no_connection_error(resp):
                return 0
            return len(resp) if isinstance(resp, list) else 0

        today_count       = _count(today_raw)
        overdue_count     = _count(overdue_raw)
        upcoming_7d_count = _count(upcoming_raw)

        recent = recent_raw if isinstance(recent_raw, list) else []
        recent_tasks = [
            {
                "task_id":    t.get("id"),
                "title":      t.get("title", "")[:80],
                "done":       t.get("done", False),
                "due_date":   (t.get("due_date") or "")[:10],
                "project_id": t.get("project_id"),
                "bucket_id":  t.get("bucket_id"),
                "assignees":  [a.get("username") for a in (t.get("assignees") or [])],
            }
            for t in recent
        ]

        projects = projects_raw if isinstance(projects_raw, list) else []
        active_projects = [p for p in projects if not p.get("is_archived", False)]
        favorites = [p for p in active_projects if p.get("is_favorite", False)]

        # Fetch kanban views for up to 5 active projects (avoid N+1 overload at 30s tick)
        top_projects = active_projects[:5]
        if top_projects:
            views_results = await asyncio.gather(
                *[
                    api_get(ctx, f"/v1/projects/{p['id']}/views", {"imperal_id": imperal_id})
                    for p in top_projects
                ],
                return_exceptions=True,
            )
        else:
            views_results = []

        kanban_view_ids: dict[int, int] = {}
        for p, result in zip(top_projects, views_results):
            if isinstance(result, list):
                for v in result:
                    if v.get("view_kind") in _KANBAN_VIEW_KINDS:
                        kanban_view_ids[p["id"]] = v["id"]
                        break

        if kanban_view_ids:
            bucket_results = await asyncio.gather(
                *[
                    api_get(ctx, f"/v1/projects/{pid}/views/{vid}/buckets", {"imperal_id": imperal_id})
                    for pid, vid in kanban_view_ids.items()
                ],
                return_exceptions=True,
            )
        else:
            bucket_results = []

        buckets_per_project: dict[int, list] = {}
        for (pid, _), result in zip(kanban_view_ids.items(), bucket_results):
            if isinstance(result, list):
                buckets_per_project[pid] = [
                    {"bucket_id": b["id"], "title": b.get("title", "?")}
                    for b in result
                ]

        users = users_raw if isinstance(users_raw, list) else []

        return {"response": {
            "connected":              True,
            "today_count":            today_count,
            "overdue_count":          overdue_count,
            "upcoming_7d_count":      upcoming_7d_count,
            "active_projects_count":  len(active_projects),
            "active_projects": [
                {
                    "project_id": p["id"],
                    "title":      p.get("title", ""),
                    **({"buckets": buckets_per_project[p["id"]]} if p["id"] in buckets_per_project else {}),
                }
                for p in active_projects[:20]
            ],
            "favorite_projects": [
                {"project_id": p["id"], "title": p.get("title", "")}
                for p in favorites[:5]
            ],
            "team_members": [
                {"username": u.get("username"), "connected": u.get("connected", False)}
                for u in users[:20]
            ],
            "recent_tasks": recent_tasks,
        }}
    except Exception as e:
        log.error("skeleton_refresh_tasks failed: %s", e)
        return {"response": {}}


@ext.tool(
    "skeleton_alert_tasks",
    description="Alert on new overdue tasks or today's task count changes.",
)
async def skeleton_alert_tasks(
    ctx,
    old: dict | None = None,
    new: dict | None = None,
) -> dict:
    """Called by kernel when tasks snapshot changes between ticks."""
    if not new:
        return {"response": ""}

    alerts: list[str] = []
    overdue     = new.get("overdue_count", 0)
    today       = new.get("today_count", 0)
    old_overdue = (old or {}).get("overdue_count", 0)

    if overdue > 0 and overdue > old_overdue:
        delta = overdue - old_overdue
        if delta == overdue:
            alerts.append(f"{overdue} task{'s' if overdue > 1 else ''} overdue")
        else:
            alerts.append(f"{delta} new overdue task{'s' if delta > 1 else ''} (now {overdue} total)")

    if today > 0 and today != (old or {}).get("today_count", 0):
        alerts.append(f"{today} task{'s' if today > 1 else ''} due today")

    if not alerts:
        return {"response": ""}

    return {"response": " · ".join(alerts)}
