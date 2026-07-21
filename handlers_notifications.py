"""tasks · Live notifications from the user's own Vikunja (webhook-driven).

Design (BYO architecture makes this simpler than github-connector's shared
GitHub App): every tasks user connects their OWN Vikunja instance
(vikunja_connections, one row per imperal_id — see handlers_connection.py).
A Vikunja *user-level* webhook (`PUT /user/settings/webhooks`, distinct from
the per-project kind) fires for every project on THAT instance alone — so,
unlike github-connector's shared installation, there is no cross-user event
leakage to guard against: every delivery to a given registration is
inherently about the one user who registered it.

Flow:
1. `enable_task_notifications` (authenticated) generates an opaque token
   (embedded in the target URL query string, e.g. `?t=<token>`) and a
   separate HMAC secret, asks vikunja-bridge to register a user-level
   webhook pointed at `ctx.webhook_url("vikunja_events")?t=<token>`, then
   saves {webhook_id, token, secret, events} in the user's OWN store
   partition (so the panel can show/disable it later) AND a token -> real
   imperal_id reverse index under the shared "__webhook__" partition — the
   same two-collection trick github-connector's storage.py uses for its
   install-flow state, needed here because the inbound webhook handler has
   no identity of its own (`ctx.user.imperal_id == "__webhook__"`).
2. Vikunja POSTs to that target URL on every subscribed event, signing the
   raw body with the secret we gave it (`X-Vikunja-Signature`, HMAC-SHA256,
   per vikunja.io/docs/webhooks). `vikunja_events` resolves `t` from
   query_params against the reverse index to find (imperal_id, secret),
   verifies the signature, and — only for a small notification-worthy
   subset of event names — calls `ctx.notify(...)` rescoped to that real
   user (same `_notify_for` rebuild trick as github-connector).
3. `disable_task_notifications` unregisters the webhook on Vikunja's side
   and deletes both store rows.

Non-goals (v1): no per-event-type toggle UI (a fixed sensible default set —
assigned + commented — ships; the full curated list Vikunja allows is
visible via `events` in the enable response for anyone who wants to see
what's subscribed). No filtering "did I do this to myself" — since this is
the user's own private Vikunja, every event genuinely is about them, so
that self-action noise concern (real for github-connector's shared repos)
doesn't apply here the same way.
"""

import hashlib
import hmac
import logging
import secrets as _secrets_mod

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, chat, ext, imperal_id_of
from handlers_crud import _require_user, _bridge_error_msg
from models_return import NotificationStatusResult, EnableNotificationsResult, DisableNotificationsResult
from error_codes import (
    TASKS_BRIDGE_ERROR,
    TASKS_NOTIFICATIONS_ALREADY_ENABLED,
    TASKS_NOTIFICATIONS_NOT_ENABLED,
)

log = logging.getLogger("tasks")

# Vikunja event names confirmed to exist (pkg/models/events.go /
# vikunja.io/docs/webhooks) — the v1 default notify-worthy subset.
_DEFAULT_EVENTS = ["task.assignee.created", "task.comment.created"]

_STATE_COLLECTION = "tasks_notify_state"          # user's own partition
_INDEX_COLLECTION = "tasks_webhook_index"         # shared "__webhook__" partition


class EnableNotificationsParams(BaseModel):
    events: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_EVENTS),
        description=(
            "Vikunja event names to notify on. Defaults to being assigned a task and "
            "someone commenting on one. Advanced users can pass a longer list."
        ),
    )


class NoParams(BaseModel):
    pass


def _store_for(ctx, user_id: str):
    """Same rebuild-the-client trick as github-connector's storage._store_for —
    only user_id differs, gateway/auth/tenant wiring is reused as-is."""
    if not hasattr(ctx.store, "_gateway_url"):
        return ctx.store  # MockStore in tests — no per-user partitioning to rebuild
    from imperal_sdk.store.client import StoreClient
    return StoreClient(
        gateway_url=ctx.store._gateway_url,
        service_token=ctx.store._auth_token,
        extension_id=ctx.store._extension_id,
        user_id=user_id,
        tenant_id=ctx.store._tenant_id,
    )


def _notify_for(webhook_ctx, imperal_id: str):
    """Rebuild ctx.notify scoped to a real user — mirrors github-connector's
    handlers_webhook_events._notify_for (ctx.notify here is "__webhook__"-scoped)."""
    if not hasattr(webhook_ctx.notify, "_gateway_url"):
        return webhook_ctx.notify  # test double
    from imperal_sdk.notify.client import NotifyClient
    return NotifyClient(
        gateway_url=webhook_ctx.notify._gateway_url,
        service_token=webhook_ctx.notify._auth_token,
        user_id=imperal_id,
        extension_id=getattr(webhook_ctx.notify, "_extension_id", "tasks"),
    )


async def _get_own_state(ctx):
    page = await ctx.store.query(_STATE_COLLECTION, limit=1)
    return page.data[0] if page.data else None


@chat.function(
    "get_notification_status",
    action_type="read",
    effects=[],
    description="Check whether live Vikunja notifications (assigned/commented) are enabled.",
    data_model=NotificationStatusResult,
)
async def get_notification_status(ctx, params: NoParams) -> ActionResult:
    """Return whether the current user has live notifications enabled."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    doc = await _get_own_state(ctx)
    if not doc:
        return ActionResult.success(summary="Live task notifications are off.", data={"enabled": False})
    return ActionResult.success(
        summary=f"Live task notifications are on ({', '.join(doc.data.get('events', []))}).",
        data={"enabled": True, "webhook_id": doc.data.get("webhook_id"), "events": doc.data.get("events", [])},
    )


@chat.function(
    "enable_task_notifications",
    action_type="write",
    effects=["update:notification_settings"],
    event="task.notifications_enabled",
    description=(
        "Turn on live notifications from your Vikunja — get notified in Imperal (bell/telegram, "
        "per your notification settings) when someone assigns you a task or comments on one. "
        "Registers a webhook on your own Vikunja instance automatically — no manual setup needed."
    ),
    data_model=EnableNotificationsResult,
)
async def enable_task_notifications(ctx, params: EnableNotificationsParams) -> ActionResult:
    """Register a user-level Vikunja webhook pointed at this extension."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    existing = await _get_own_state(ctx)
    if existing:
        return ActionResult.error(
            "Notifications are already enabled. Disable them first to change the event list.",
            code=TASKS_NOTIFICATIONS_ALREADY_ENABLED,
        )

    token = _secrets_mod.token_urlsafe(24)
    secret = _secrets_mod.token_urlsafe(32)
    target_url = f"{ctx.webhook_url('vikunja_events')}?t={token}"

    resp = await api_post(ctx, "/v1/webhooks", {
        "imperal_id": imperal_id, "target_url": target_url,
        "events": params.events, "secret": secret,
    })
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't register Vikunja webhook"), code=TASKS_BRIDGE_ERROR)

    webhook_id = resp.get("id") if isinstance(resp, dict) else None

    await ctx.store.create(_STATE_COLLECTION, {
        "webhook_id": webhook_id, "token": token, "events": params.events,
    })
    index_store = _store_for(ctx, "__webhook__")
    await index_store.create(_INDEX_COLLECTION, {
        "token": token, "imperal_id": imperal_id, "secret": secret,
    })

    return ActionResult.success(
        summary=f"Live task notifications are on ({', '.join(params.events)}).",
        data={"enabled": True, "webhook_id": webhook_id, "events": params.events, "refresh_panels": ["sidebar"]},
    )


@chat.function(
    "disable_task_notifications",
    action_type="write",
    effects=["update:notification_settings"],
    event="task.notifications_disabled",
    description="Turn off live Vikunja notifications and remove the webhook from your Vikunja instance.",
    data_model=DisableNotificationsResult,
)
async def disable_task_notifications(ctx, params: NoParams) -> ActionResult:
    """Unregister the Vikunja webhook and clear stored notification state."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    doc = await _get_own_state(ctx)
    if not doc:
        return ActionResult.error("Notifications are not currently enabled.", code=TASKS_NOTIFICATIONS_NOT_ENABLED)

    webhook_id = doc.data.get("webhook_id")
    token = doc.data.get("token")

    if webhook_id:
        resp = await api_delete(ctx, f"/v1/webhooks/{webhook_id}", params={"imperal_id": imperal_id})
        if isinstance(resp, dict) and resp.get("status") == "error":
            log.warning("disable_task_notifications: bridge delete failed, clearing local state anyway: %s", resp)

    await ctx.store.delete(_STATE_COLLECTION, doc.id)

    if token:
        index_store = _store_for(ctx, "__webhook__")
        existing = await index_store.query(_INDEX_COLLECTION, where={"token": token}, limit=1)
        if existing.data:
            await index_store.delete(_INDEX_COLLECTION, existing.data[0].id)

    return ActionResult.success(
        summary="Live task notifications are off.",
        data={"enabled": False, "refresh_panels": ["sidebar"]},
    )


def _verify_signature(secret: str, body: str, signature_header: str) -> bool:
    """Vikunja's documented HMAC-SHA256 check over the raw body, constant-time
    compare — same shape as github-connector's X-Hub-Signature-256 check,
    header name and hex format differ (no 'sha256=' prefix per Vikunja docs)."""
    if not signature_header:
        return False
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _describe_event(event_name: str, data: dict) -> str | None:
    """Return a notification message for a notification-worthy event, or
    None to skip silently (event type not in our curated v1 set)."""
    task = data.get("task") or {}
    title = task.get("title", "a task")
    if event_name == "task.assignee.created":
        return f"You were assigned to \"{title}\"."
    if event_name == "task.comment.created":
        return f"New comment on \"{title}\"."
    return None


@ext.webhook("vikunja_events", method="POST", secret_header="X-Vikunja-Signature")
async def vikunja_events(ctx, headers: dict, body: str, query_params: dict) -> dict:
    """Receive a signed Vikunja webhook delivery and notify the right user.

    Unauthenticated per @ext.webhook's contract — HMAC verification below
    (against the per-registration secret found via the opaque `t` token) is
    the only trust boundary. `ctx.notify` here is "__webhook__"-scoped;
    `_notify_for` rebuilds it for the real recipient, same as
    github-connector's handlers_webhook_events.
    """
    import json

    token = query_params.get("t", "")
    if not token:
        return {"status": "ignored", "reason": "missing token"}

    index_store = _store_for(ctx, "__webhook__")
    page = await index_store.query(_INDEX_COLLECTION, where={"token": token}, limit=1)
    if not page.data:
        return {"status": "ignored", "reason": "unknown token"}

    record = page.data[0].data
    imperal_id = record.get("imperal_id", "")
    secret = record.get("secret", "")

    signature = headers.get("x-vikunja-signature", "") or headers.get("X-Vikunja-Signature", "")
    if not _verify_signature(secret, body, signature):
        log.warning("vikunja_events: signature mismatch, dropping delivery")
        return {"status": "rejected", "reason": "invalid signature"}

    try:
        payload = json.loads(body)
    except Exception:
        return {"status": "ignored", "reason": "invalid JSON"}

    event_name = payload.get("event_name", "")
    message = _describe_event(event_name, payload.get("data") or {})
    if message is None:
        return {"status": "ignored", "reason": f"event '{event_name}' not notification-worthy in v1"}

    notify = _notify_for(ctx, imperal_id)
    await notify(message, priority="normal", channel="in_app")
    return {"status": "notified", "event": event_name}
