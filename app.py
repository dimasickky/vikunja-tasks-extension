"""tasks · ChatExtension + thin HTTP client to the backend service.

v3.0.0 — SDK 4.0.1 federal contract. ctx.http replaces the module-level
httpx.AsyncClient singleton; all api_*(ctx, ...) helpers are ctx-scoped
and per-request clean.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult  # noqa: F401 — re-exported


class NoParams(BaseModel):
    """Empty Pydantic params model for no-arg @chat.function handlers (V17 compliance)."""
    pass

log = logging.getLogger("tasks")


# ─── Config ───────────────────────────────────────────────────────────────── #

def _bridge_url() -> str:
    url = os.getenv("VIKUNJA_BRIDGE_URL", "")
    if not url:
        raise RuntimeError("VIKUNJA_BRIDGE_URL env var not set")
    return url.rstrip("/")


def _bridge_key() -> str:
    return os.getenv("VIKUNJA_BRIDGE_KEY", "")


def _auth_headers() -> dict:
    key = _bridge_key()
    return {"x-api-key": key} if key else {}


# ─── Identity helpers ─────────────────────────────────────────────────────── #

def imperal_id_of(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user:
        return ctx.user.imperal_id
    return ""


def require_imperal_id(ctx) -> str:
    iid = imperal_id_of(ctx)
    if not iid:
        raise RuntimeError(
            "No authenticated user on context. Refusing to call the backend service "
            "with an empty imperal_id."
        )
    return iid


# ─── Bridge API helpers (ctx-scoped, per-request, no shared state) ────────── #

def _extract_error(resp) -> dict:
    """Normalise non-2xx SDK HTTPResponse from bridge."""
    body = resp.body
    if isinstance(body, dict):
        detail = body.get("detail", str(body))
    elif isinstance(body, str):
        detail = body or f"HTTP {resp.status_code}"
    else:
        detail = f"HTTP {resp.status_code}"
    return {"status": "error", "detail": detail, "http_status": resp.status_code}


async def api_post(ctx, path: str, data: dict) -> dict:
    r = await ctx.http.post(f"{_bridge_url()}{path}", json=data, headers=_auth_headers())
    if not r.ok:
        return _extract_error(r)
    body = r.body
    return body if isinstance(body, dict) else {}


async def api_get(ctx, path: str, params: dict | None = None) -> dict | list:
    r = await ctx.http.get(f"{_bridge_url()}{path}", params=params or {}, headers=_auth_headers())
    if not r.ok:
        return _extract_error(r)
    body = r.body
    return body if (isinstance(body, dict) or isinstance(body, list)) else {}


async def api_delete(ctx, path: str, params: dict | None = None) -> dict:
    r = await ctx.http.delete(f"{_bridge_url()}{path}", params=params or {}, headers=_auth_headers())
    if not r.ok:
        return _extract_error(r)
    body = r.body
    return body if isinstance(body, dict) else {}


def is_no_connection_error(resp: dict) -> bool:
    """Bridge returns HTTP 412 when the user has no Vikunja connection."""
    return isinstance(resp, dict) and resp.get("http_status") == 412


# ─── System Prompt ────────────────────────────────────────────────────────── #

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text()


# ─── Extension ───────────────────────────────────────────────────────────── #

ext = Extension(
    "tasks",
    version="3.1.0",
    capabilities=["tasks:read", "tasks:write"],
    display_name="Tasks",
    description=(
        "Kanban task manager connecting to your own Vikunja instance — "
        "create, assign, filter tasks and manage projects and labels."
    ),
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(
    ext=ext,
    tool_name="tool_tasks_chat",
    description=(
        "Tasks manager — kanban boards, projects, due dates, labels, "
        "assignees, comments. Each user connects their own Vikunja "
        "instance; data lives in the user's Vikunja, never on our side. "
        "When invoking this tool, pass the user's request verbatim as "
        "`message`; the extension dispatches to typed @chat.function handlers."
    ),
    system_prompt=SYSTEM_PROMPT,
)


# ─── Lifecycle ────────────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await ctx.http.get(f"{_bridge_url()}/health", headers=_auth_headers())
        if not r.ok:
            return {"status": "degraded", "version": ext.version, "bridge": "unreachable"}
        body = r.body if isinstance(r.body, dict) else {}
        return {"status": "ok", "version": ext.version, "bridge": body.get("status")}
    except Exception:
        return {"status": "degraded", "version": ext.version, "bridge": "unreachable"}
