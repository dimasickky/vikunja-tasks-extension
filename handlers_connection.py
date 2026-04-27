"""tasks · BYO connection handlers (connect / disconnect / status).

Thin chat-function wrappers that proxy to the backend service:
    POST   /v1/connect           username + password → mints PAT on bridge
    POST   /v1/connect/with-pat  user pastes a ready PAT
    DELETE /v1/connect           revoke + delete
    GET    /v1/connection        status (no PAT echoed)

The user's password and PAT plaintext NEVER touch this extension's stack
beyond the single chat-function call frame — they're forwarded immediately
to the bridge via httpx and discarded after the request returns. The
bridge is the only place that holds plaintext during the request, and
the only place that stores the encrypted form at rest.
"""
from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, api_get, chat, require_imperal_id


_MODEL_CONFIG = ConfigDict(populate_by_name=True)


# ─── Params ────────────────────────────────────────────────────────────── #

class ConnectVikunjaParams(BaseModel):
    """Connect via username + password (default flow)."""
    model_config = _MODEL_CONFIG

    base_url: str = Field(
        default="",
        description="Your Vikunja base URL, e.g. https://vikunja.example.com",
        validation_alias=AliasChoices("base_url", "url", "vikunja_url", "host", "instance"),
    )
    username: str = Field(
        default="",
        description="Your Vikunja username.",
        validation_alias=AliasChoices("username", "user", "login"),
    )
    password: str = Field(
        default="",
        description="Your Vikunja password (used once to mint a long-lived API token, never stored).",
        validation_alias=AliasChoices("password", "pass", "passwd"),
    )


class ConnectVikunjaWithPatParams(BaseModel):
    """Advanced: user pastes a pre-existing PAT minted in their Vikunja UI."""
    model_config = _MODEL_CONFIG

    base_url: str = Field(
        default="",
        validation_alias=AliasChoices("base_url", "url", "vikunja_url", "host", "instance"),
    )
    pat: str = Field(
        default="",
        description="Vikunja Personal Access Token (Settings → API tokens).",
        validation_alias=AliasChoices("pat", "token", "api_token", "personal_access_token"),
    )


class _NoParams(BaseModel):
    model_config = _MODEL_CONFIG


# ─── Handlers ──────────────────────────────────────────────────────────── #

@chat.function(
    "connect_vikunja",
    action_type="write",
    event="connection.created",
    description=(
        "Connect a user's Vikunja instance via username + password. "
        "The password is forwarded to the backend service once, exchanged for a "
        "long-lived Personal Access Token, and discarded. Only the encrypted "
        "PAT is stored. Returns base_url + username on success."
    ),
)
async def connect_vikunja(ctx, params: ConnectVikunjaParams) -> ActionResult:
    try:
        if not params.base_url.strip():
            return ActionResult.error("Vikunja URL is required (e.g. https://vikunja.example.com).")
        if not params.username.strip():
            return ActionResult.error("Username is required.")
        if not params.password:
            return ActionResult.error("Password is required.")

        resp = await api_post("/v1/connect", {
            "imperal_id": require_imperal_id(ctx),
            "base_url": params.base_url.strip(),
            "username": params.username.strip(),
            "password": params.password,
        })
        if resp.get("status") == "error":
            return ActionResult.error(
                _format_connect_error(resp, default="Couldn't connect to Vikunja."),
            )
        return ActionResult.success(
            data={
                "base_url": resp.get("base_url"),
                "username": resp.get("username"),
                "vikunja_user_id": resp.get("vikunja_user_id"),
                "refresh_panels": ["sidebar", "board"],
            },
            summary=f"Connected to {resp.get('base_url')} as {resp.get('username')}.",
        )
    except Exception as e:
        return ActionResult.error(f"Connect failed: {e}")


@chat.function(
    "connect_vikunja_with_pat",
    action_type="write",
    event="connection.created",
    description=(
        "Advanced connect: user pastes a pre-existing Vikunja Personal "
        "Access Token (Settings → API tokens in their Vikunja UI). The "
        "PAT is encrypted on bridge and stored at rest."
    ),
)
async def connect_vikunja_with_pat(ctx, params: ConnectVikunjaWithPatParams) -> ActionResult:
    try:
        if not params.base_url.strip():
            return ActionResult.error("Vikunja URL is required.")
        if not params.pat.strip():
            return ActionResult.error("API token is required.")

        resp = await api_post("/v1/connect/with-pat", {
            "imperal_id": require_imperal_id(ctx),
            "base_url": params.base_url.strip(),
            "pat": params.pat.strip(),
        })
        if resp.get("status") == "error":
            return ActionResult.error(
                _format_connect_error(resp, default="The token is not accepted by Vikunja."),
            )
        return ActionResult.success(
            data={
                "base_url": resp.get("base_url"),
                "username": resp.get("username"),
                "vikunja_user_id": resp.get("vikunja_user_id"),
                "refresh_panels": ["sidebar", "board"],
            },
            summary=f"Connected to {resp.get('base_url')} as {resp.get('username')}.",
        )
    except Exception as e:
        return ActionResult.error(f"Connect failed: {e}")


@chat.function(
    "disconnect_vikunja",
    action_type="destructive",
    event="connection.deleted",
    description=(
        "Disconnect from the user's Vikunja: revoke the stored API token "
        "in their instance and delete the local connection record."
    ),
)
async def disconnect_vikunja(ctx, params: _NoParams) -> ActionResult:
    try:
        resp = await api_delete("/v1/connect", {"imperal_id": require_imperal_id(ctx)})
        if resp.get("status") == "error":
            return ActionResult.error(
                _format_connect_error(resp, default="Couldn't disconnect."),
            )
        return ActionResult.success(
            data={"deleted": resp.get("deleted", True), "refresh_panels": ["sidebar", "board"]},
            summary="Disconnected from Vikunja.",
        )
    except Exception as e:
        return ActionResult.error(f"Disconnect failed: {e}")


@chat.function(
    "get_connection_status",
    action_type="read",
    description=(
        "Check whether the user has a Vikunja connected (read-only — never "
        "echoes the API token). Returns connected: bool plus base_url and "
        "username when connected."
    ),
)
async def get_connection_status(ctx, params: _NoParams) -> ActionResult:
    try:
        resp = await api_get("/v1/connection", {"imperal_id": require_imperal_id(ctx)})
        if resp.get("status") == "error":
            return ActionResult.error(
                _format_connect_error(resp, default="Couldn't read connection status."),
            )
        return ActionResult.success(
            data={
                "connected": resp.get("connected", False),
                "base_url": resp.get("base_url"),
                "username": resp.get("username"),
                "vikunja_user_id": resp.get("vikunja_user_id"),
            },
            summary=(
                f"Connected to {resp.get('base_url')} as {resp.get('username')}."
                if resp.get("connected") else
                "No Vikunja connected. Connect one in the tasks panel."
            ),
        )
    except Exception as e:
        return ActionResult.error(f"Status check failed: {e}")


# ─── Helpers ───────────────────────────────────────────────────────────── #

def _format_connect_error(resp: dict, default: str) -> str:
    """Pull a human-readable error out of bridge's normalised error shape."""
    detail = resp.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, dict):
        return detail.get("detail") or detail.get("error") or default
    return default
