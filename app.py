"""tasks · ChatExtension + bridge HTTP client + on_install provisioning."""
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


# ─── Context helpers ───────────────────────────────────────────────────── #

def _imperal_id(ctx) -> str:
    """Extract imperal_id from ctx — same pattern as other extensions."""
    if hasattr(ctx, "user") and ctx.user:
        return ctx.user.id
    return ""


# ─── Bridge API helpers ────────────────────────────────────────────────── #

def _extract_error(r: httpx.Response) -> dict:
    """Normalise error response from bridge to ActionResult-compatible shape."""
    try:
        body = r.json()
        detail = body.get("detail", r.text)
    except Exception:
        detail = r.text or f"HTTP {r.status_code}"
    return {"status": "error", "detail": detail}


async def api_post(path: str, data: dict) -> dict:
    r = await _get_http().post(path, json=data)
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json()


async def api_get(path: str, params: dict | None = None) -> dict:
    r = await _get_http().get(path, params=params or {})
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json()


async def api_delete(path: str, params: dict | None = None) -> dict:
    r = await _get_http().delete(path, params=params or {})
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json()


async def api_delete_body(path: str, data: dict) -> dict:
    """DELETE with JSON body (for /v1/account)."""
    r = await _get_http().request("DELETE", path, json=data)
    if r.status_code >= 400:
        return _extract_error(r)
    return r.json()


# ─── System Prompt ─────────────────────────────────────────────────────── #

SYSTEM_PROMPT = (Path(__file__).parent / "system_prompt.txt").read_text()


# ─── Extension ─────────────────────────────────────────────────────────── #

ext = Extension("tasks", version="1.0.0")

chat = ChatExtension(
    ext=ext,
    tool_name="tool_tasks_chat",
    description=(
        "Tasks manager — kanban boards, projects, due dates, labels, "
        "assignees, comments. AI-powered breakdown, planning, summarization."
    ),
    system_prompt=SYSTEM_PROMPT,
    model="claude-haiku-4-5-20251001",
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


# ─── Lifecycle — provision on install ──────────────────────────────────── #

@ext.on_install
async def on_install(ctx):
    """Auto-provision Vikunja user on first install.

    Bridge /v1/provision is idempotent — safe to call on every install (e.g.
    re-install after uninstall will just return existing vikunja_user_id).
    """
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        log.warning("tasks on_install called without ctx.user — skipping provision")
        return

    agency_id = None
    if hasattr(ctx, "user") and hasattr(ctx.user, "agency_id"):
        agency_id = ctx.user.agency_id

    resp = await api_post(
        "/v1/provision",
        {"imperal_id": imperal_id, "agency_id": agency_id},
    )
    if resp.get("status") == "error":
        log.error("tasks provisioning failed for %s: %s", imperal_id, resp.get("detail"))
        return

    log.info(
        "tasks provisioned for %s → vikunja_user_id=%s (created=%s)",
        imperal_id, resp.get("vikunja_user_id"), resp.get("created"),
    )


@ext.on_uninstall
async def on_uninstall(ctx):
    """GDPR-compliant cascade delete on uninstall.

    Removes Vikunja user (+ all their tasks/projects/comments) and the
    imperal_id→vuid mapping. Data-rights operation — free, no billing.
    """
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        return

    resp = await api_delete_body("/v1/account", {"imperal_id": imperal_id})
    if resp.get("status") == "error":
        log.error("tasks uninstall cleanup failed for %s: %s", imperal_id, resp.get("detail"))
        return

    log.info(
        "tasks uninstalled for %s → vuid=%s deleted=%s",
        imperal_id, resp.get("vikunja_user_id"), resp.get("deleted"),
    )
