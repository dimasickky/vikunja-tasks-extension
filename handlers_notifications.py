"""tasks · Live notifications from the user's own Vikunja (webhook-driven).

v1.1.0 shipped this against Vikunja's *user-level* webhook endpoint
(`/user/settings/webhooks`) — a dead end discovered during live smoke-testing
right after deploy: Vikunja's own route registration puts the ENTIRE
`/user/...` group outside the API-token permission system
(`CollectRoutesForAPITokenUsage` skips any route under the `user_` group
unconditionally), so no Personal Access Token can ever call it, no matter
what scopes are granted. This bridge only ever holds a PAT, never a full
login JWT (see routes_connection.py) — a session-based redesign was ruled
out as far riskier than switching primitives.

v1.2.0 (this version) uses *project-level* webhooks instead
(`/projects/{id}/webhooks`), which DO live under the plain, token-permitted
routes group. The trade-off: there's no single "whole account" registration
anymore, so `enable_task_notifications` fans out — it registers one webhook
per project the user currently owns, all pointed at the same
`ctx.webhook_url(...)` target with the same opaque token + secret. The user
still only sees ONE toggle; the fan-out is entirely hidden in this handler.
New projects created *after* enabling won't auto-get a webhook — a known v1
limitation, noted in get_notification_status's response.

Flow:
1. `enable_task_notifications` (authenticated) lists the user's projects,
   generates one opaque token + one HMAC secret, and registers a webhook on
   EACH project via vikunja-bridge's routes_webhooks.py, collecting
   {project_id, webhook_id} pairs. Saves {registrations, token, events} in
   the user's OWN store partition (so the panel can show/disable it later)
   AND a token -> real imperal_id + secret reverse index under the shared
   "__webhook__" partition — the same two-collection trick github-connector's
   storage.py uses for its install-flow state, needed here because the
   inbound webhook handler has no identity of its own
   (`ctx.user.imperal_id == "__webhook__"`).
2. Vikunja POSTs to that target URL on every subscribed event on any of
   those projects, signing the raw body with the secret we gave it
   (`X-Vikunja-Signature`, HMAC-SHA256, per vikunja.io/docs/webhooks).
   `vikunja_events` resolves `t` from query_params against the reverse
   index to find (imperal_id, secret), verifies the signature, and — only
   for a small notification-worthy subset of event names — calls
   `ctx.notify(...)` rescoped to that real user (same `_notify_for` rebuild
   trick as github-connector).
3. `disable_task_notifications` unregisters every stored (project_id,
   webhook_id) pair and deletes both store rows. Best-effort: a project
   deleted in the meantime just 404s on unregister, which is logged and
   skipped rather than blocking the rest of the cleanup.

Non-goals (v1): no per-event-type toggle UI (a fixed sensible default set —
assigned + commented — ships; the full curated list Vikunja allows is
visible via `events` in the enable response for anyone who wants to see
what's subscribed). No auto-registration on newly created projects after
enabling (documented limitation above). No filtering "did I do this to
myself" — since this is the user's own private Vikunja, every event
genuinely is about them, so that self-action noise concern (real for
github-connector's shared repos) doesn't apply here the same way.
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
    """Re-scope ctx.store to another user via the SDK's public
    ``StoreClient.for_user`` (imperal-sdk >= 5.9.22) — replaces the old
    rebuild-from-private-attributes trick. MockStore in tests has no
    ``for_user`` (it never crosses a real user boundary) — fall back to
    ctx.store itself."""
    if not hasattr(ctx.store, "for_user"):
        return ctx.store  # MockStore in tests — no per-user partitioning to rebuild
    return ctx.store.for_user(user_id)


def _notify_for(webhook_ctx, imperal_id: str):
    """Re-scope ctx.notify to a real user via ``NotifyClient.for_user``
    (imperal-sdk >= 5.9.22) — ctx.notify here is "__webhook__"-scoped and
    ctx.as_user() needs system context. MockNotify in tests has no
    ``for_user`` and is returned as-is."""
    if not hasattr(webhook_ctx.notify, "for_user"):
        return webhook_ctx.notify  # test double
    return webhook_ctx.notify.for_user(imperal_id)


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
    regs = doc.data.get("registrations", [])
    return ActionResult.success(
        summary=(
            f"Live task notifications are on ({', '.join(doc.data.get('events', []))}), "
            f"covering {len(regs)} project(s) as of when you enabled them."
        ),
        data={"enabled": True, "webhook_id": None, "events": doc.data.get("events", [])},
    )


@chat.function(
    "enable_task_notifications",
    action_type="write",
    effects=["update:notification_settings"],
    event="task.notifications_enabled",
    description=(
        "Turn on live notifications from your Vikunja — get notified in Imperal (bell/telegram, "
        "per your notification settings) when someone assigns you a task or comments on one. "
        "Registers a webhook on every one of your current Vikunja projects automatically — "
        "no manual setup needed. Projects created after enabling won't be covered until you "
        "disable and re-enable."
    ),
    data_model=EnableNotificationsResult,
)
async def enable_task_notifications(ctx, params: EnableNotificationsParams) -> ActionResult:
    """Register a webhook on every current project, pointed at this extension."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    existing = await _get_own_state(ctx)
    if existing:
        return ActionResult.error(
            "Notifications are already enabled. Disable them first to change the event list.",
            code=TASKS_NOTIFICATIONS_ALREADY_ENABLED,
        )

    projects_resp = await api_get(ctx, "/v1/projects", {"imperal_id": imperal_id})
    projects = projects_resp if isinstance(projects_resp, list) else []
    if not projects:
        return ActionResult.error(
            "You don't have any Vikunja projects yet — create one first.", code=TASKS_BRIDGE_ERROR,
        )

    token = _secrets_mod.token_urlsafe(24)
    secret = _secrets_mod.token_urlsafe(32)
    target_url = f"{ctx.webhook_url('vikunja_events')}?t={token}"

    registrations = []
    failures = []
    for proj in projects:
        project_id = proj.get("id")
        if project_id is None:
            continue
        resp = await api_post(ctx, f"/v1/webhooks/projects/{project_id}", {
            "imperal_id": imperal_id, "target_url": target_url,
            "events": params.events, "secret": secret,
        })
        if isinstance(resp, dict) and resp.get("status") == "error":
            failures.append(project_id)
            continue
        webhook_id = resp.get("id") if isinstance(resp, dict) else None
        if webhook_id is not None:
            registrations.append({"project_id": project_id, "webhook_id": webhook_id})

    if not registrations:
        return ActionResult.error(
            _bridge_error_msg({}, "Couldn't register a webhook on any project"), code=TASKS_BRIDGE_ERROR,
        )

    await ctx.store.create(_STATE_COLLECTION, {
        "registrations": registrations, "token": token, "events": params.events,
    })
    index_store = _store_for(ctx, "__webhook__")
    await index_store.create(_INDEX_COLLECTION, {
        "token": token, "imperal_id": imperal_id, "secret": secret,
    })

    summary = f"Live task notifications are on ({', '.join(params.events)}) for {len(registrations)} project(s)."
    if failures:
        summary += f" ({len(failures)} project(s) failed to register and were skipped.)"

    return ActionResult.success(
        summary=summary,
        data={
            "enabled": True, "webhook_id": registrations[0]["webhook_id"] if registrations else 0,
            "events": params.events, "refresh_panels": ["sidebar"],
        },
    )


@chat.function(
    "disable_task_notifications",
    action_type="write",
    effects=["update:notification_settings"],
    event="task.notifications_disabled",
    description="Turn off live Vikunja notifications and remove the webhooks from your Vikunja projects.",
    data_model=DisableNotificationsResult,
)
async def disable_task_notifications(ctx, params: NoParams) -> ActionResult:
    """Unregister every stored per-project webhook and clear notification state."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    doc = await _get_own_state(ctx)
    if not doc:
        return ActionResult.error("Notifications are not currently enabled.", code=TASKS_NOTIFICATIONS_NOT_ENABLED)

    registrations = doc.data.get("registrations", [])
    token = doc.data.get("token")

    for reg in registrations:
        project_id = reg.get("project_id")
        webhook_id = reg.get("webhook_id")
        if project_id is None or webhook_id is None:
            continue
        resp = await api_delete(
            ctx, f"/v1/webhooks/projects/{project_id}/{webhook_id}", params={"imperal_id": imperal_id},
        )
        if isinstance(resp, dict) and resp.get("status") == "error":
            log.warning(
                "disable_task_notifications: bridge delete failed for project %s webhook %s, "
                "continuing cleanup anyway: %s", project_id, webhook_id, resp,
            )

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
    github-connector's handlers_webhook_events. One delivery can come from
    any of the user's projects (fan-out registration) but always carries
    the same `t` token, so identity resolution is unchanged either way.
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
