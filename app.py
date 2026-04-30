"""tasks · ChatExtension + thin HTTP client to the backend service.

v2.0.0 — BYO Vikunja. The shared-instance provisioning flow is gone:
no `on_install` auto-create, no `on_uninstall` cascade delete. Each user
connects their own Vikunja in the panel; the bridge stores an encrypted
PAT and resolves it per call.

The extension stays thin: it owns business logic + chat surface + UI,
and delegates ALL HTTP / encryption / external-system logic to
the backend service (the backend host:8102) — same workspace pattern as
notes → the backend and sql-db → the backend.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult

log = logging.getLogger("tasks")


# ─── Config (lazy — validator loads main.py before secrets are set) ────── #

def _bridge_url() -> str:
    url = os.getenv("VIKUNJA_BRIDGE_URL", "")
    if not url:
        raise RuntimeError("VIKUNJA_BRIDGE_URL env var not set")
    return url


def _bridge_key() -> str:
    return os.getenv("VIKUNJA_BRIDGE_KEY", "")


# ─── HTTP client (singleton) ───────────────────────────────────────────── #

_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=_bridge_url(),
            headers={"x-api-key": _bridge_key()},
            timeout=30.0,
        )
    return _http


# ─── Identity helpers ──────────────────────────────────────────────────── #

def _imperal_id(ctx) -> str:
    """Extract imperal_id from ctx — same pattern as other Dimasickky extensions."""
    if hasattr(ctx, "user") and ctx.user:
        return ctx.user.imperal_id
    return ""


def require_imperal_id(ctx) -> str:
    """Returns ctx.user.imperal_id or raises. Use from every @chat.function."""
    iid = _imperal_id(ctx)
    if not iid:
        raise RuntimeError(
            "No authenticated user on context. Refusing to call the backend service "
            "with an empty imperal_id."
        )
    return iid


# ─── Bridge API helpers ────────────────────────────────────────────────── #

# Bridge contract: success → JSON object, error → HTTP 4xx/5xx with JSON
# body `{"detail": "..."}`. We translate any 4xx/5xx into a uniform shape
# `{"status": "error", "detail": "...", "http_status": N}` so handlers can
# surface clean ActionResult.error without duplicating boilerplate.

def _extract_error(r: httpx.Response) -> dict:
    """Normalise non-2xx response from bridge to ActionResult-compatible shape."""
    try:
        body = r.json()
        detail = body.get("detail", r.text)
    except Exception:
        detail = r.text or f"HTTP {r.status_code}"
    return {"status": "error", "detail": detail, "http_status": r.status_code}


async def api_post(path: str, data: dict) -> dict:
    r = await _get_http().post(path, json=data)
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json() if r.content else {}


async def api_get(path: str, params: dict | None = None) -> dict:
    r = await _get_http().get(path, params=params or {})
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json() if r.content else {}


async def api_delete(path: str, params: dict | None = None) -> dict:
    r = await _get_http().delete(path, params=params or {})
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json() if r.content else {}


def is_no_connection_error(resp: dict) -> bool:
    """Bridge returns HTTP 412 when the user has no Vikunja connection.

    Handlers use this to surface a panel-style "Connect Vikunja first"
    message rather than a generic "couldn't fetch" error.
    """
    return isinstance(resp, dict) and resp.get("http_status") == 412


# ─── System Prompt ─────────────────────────────────────────────────────── #

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text()


# ─── Extension ─────────────────────────────────────────────────────────── #

ext = Extension("tasks", version="2.0.23")

chat = ChatExtension(
    ext=ext,
    tool_name="tool_tasks_chat",
    description=(
        "Tasks manager — kanban boards, projects, due dates, labels, "
        "assignees, comments. Each user connects their own Vikunja "
        "instance; data lives in the user's Vikunja, never on our side."
    ),
    system_prompt=SYSTEM_PROMPT,
)


# ─── Health Check ──────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await _get_http().get("/health")
        data = r.json()
        return {"status": "ok", "version": ext.version, "bridge": data.get("status")}
    except Exception:
        return {"status": "degraded", "version": ext.version, "bridge": "unreachable"}
