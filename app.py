"""tasks · TasksExtension instance, vikunja-bridge HTTP client, lifecycle.

Module-level ``ext`` is the Extension instance the kernel loader discovers
(duck-typed by ``.tools: dict`` + ``.signals``). All panels, skeleton and
lifecycle hooks bind against this instance.

Config is lazy: ``_bridge_url()`` / ``_bridge_key()`` read env vars only on
first HTTP call so the loader can import ``main.py`` before secrets are set
(validator / import-time inspection path).
"""
from __future__ import annotations

import logging
import os

import httpx

from tools import TasksExtension

log = logging.getLogger("tasks")


# ─── Config (lazy) ───────────────────────────────────────────────────── #

def _bridge_url() -> str:
    url = os.getenv("VIKUNJA_BRIDGE_URL", "")
    if not url:
        raise RuntimeError("VIKUNJA_BRIDGE_URL env var not set")
    return url


def _bridge_key() -> str:
    return os.getenv("VIKUNJA_BRIDGE_KEY", "")


# ─── HTTP client (singleton, lazy) ───────────────────────────────────── #
#
# Raw httpx kept (instead of SDK HTTPClient) because vikunja-bridge expects
# ``imperal_id`` in the JSON body for mutations and in query params for
# reads. The raw client here is still per-extension-process-scoped and
# authenticated via static ``x-api-key`` — no tenant-state bleed because
# every request carries its own ``imperal_id`` which the bridge uses to
# resolve the Vikunja user and mint a per-request JWT.

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


# ─── Identity ────────────────────────────────────────────────────────── #

def _imperal_id(ctx) -> str:
    """Return ctx.user.id or '' (panel / skeleton tolerate anonymous).

    Tools invoke ``TasksExtension._uid(ctx)`` which raises on empty so a
    missing ctx.user surfaces as a classified tool error rather than a
    silent wrong-user operation.
    """
    if hasattr(ctx, "user") and ctx.user:
        return ctx.user.id
    return ""


# ─── Bridge API helpers ──────────────────────────────────────────────── #

def _error_envelope(r: httpx.Response) -> dict:
    """Normalise the bridge's error shape to {status:error, detail:<msg>}.

    The bridge always returns JSON; fall back to raw text only when JSON
    parsing fails so we never swallow a useful error message.
    """
    try:
        body = r.json()
        detail = body.get("detail", r.text)
    except Exception:
        detail = r.text or f"HTTP {r.status_code}"
    return {"status": "error", "detail": detail}


async def api_post(path: str, data: dict) -> dict:
    r = await _get_http().post(path, json=data)
    if r.status_code >= 400:
        return _error_envelope(r)
    return r.json()


async def api_get(path: str, params: dict | None = None) -> dict:
    r = await _get_http().get(path, params=params or {})
    if r.status_code >= 400:
        return _error_envelope(r)
    return r.json()


async def api_delete(path: str, params: dict | None = None) -> dict:
    r = await _get_http().delete(path, params=params or {})
    if r.status_code >= 400:
        return _error_envelope(r)
    return r.json()


async def api_delete_body(path: str, data: dict) -> dict:
    """DELETE with JSON body — used for /v1/account cascade removal."""
    r = await _get_http().request("DELETE", path, json=data)
    if r.status_code >= 400:
        return _error_envelope(r)
    return r.json()


# ─── Extension instance (loader entry point) ─────────────────────────── #

ext = TasksExtension(
    app_id="tasks",
    version="2.0.0",
    capabilities=["tasks:read", "tasks:write"],
)


# ─── Health ──────────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await _get_http().get("/health")
        if r.status_code >= 400:
            return {"status": "degraded", "version": ext.version, "bridge": "unreachable"}
        data = r.json()
        return {"status": "ok", "version": ext.version, "bridge": data.get("status")}
    except Exception:
        return {"status": "degraded", "version": ext.version, "bridge": "unreachable"}


# ─── Lifecycle: provision on install, cascade delete on uninstall ────── #

@ext.on_install
async def on_install(ctx):
    """Auto-provision a Vikunja user on first install.

    Bridge /v1/provision is idempotent — safe to call on every install
    (re-install after uninstall returns the existing vikunja_user_id).
    """
    imperal_id = _imperal_id(ctx)
    if not imperal_id:
        log.warning("tasks on_install without ctx.user — skipping provisioning")
        return

    agency_id = None
    if hasattr(ctx, "user") and hasattr(ctx.user, "agency_id"):
        agency_id = ctx.user.agency_id

    resp = await api_post(
        "/v1/provision", {"imperal_id": imperal_id, "agency_id": agency_id},
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
    """GDPR-compliant cascade delete.

    Removes the Vikunja user, all their tasks / projects / comments, and
    the imperal_id → vuid mapping on the bridge. Free, no billing — this
    is a data-rights operation.
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
