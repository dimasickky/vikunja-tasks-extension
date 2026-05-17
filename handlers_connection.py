"""tasks · BYO connection handlers (connect / disconnect / status)."""

import logging

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_delete, api_get, chat, require_imperal_id, NoParams
from models_return import VikunjaConnectionResult, DisconnectResult, ConnectionStatusResult

log = logging.getLogger("tasks")

_MODEL_CONFIG = ConfigDict(populate_by_name=True)


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


def _format_connect_error(resp: dict, default: str) -> str:
    detail = resp.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail
    if isinstance(detail, dict):
        return detail.get("detail") or detail.get("error") or default
    return default


@chat.function(
    "connect_vikunja",
    action_type="write",
    chain_callable=True,
    effects=["create:connection"],
    event="connection.created",
    description=(
        "Connect a user's Vikunja instance via username + password. "
        "The password is forwarded to the backend service once, exchanged for a "
        "long-lived Personal Access Token, and discarded. Only the encrypted "
        "PAT is stored. Returns base_url + username on success."
    ),
    data_model=VikunjaConnectionResult,
)
async def connect_vikunja(ctx, params: ConnectVikunjaParams) -> ActionResult:
    try:
        if not params.base_url.strip():
            return ActionResult.error("Vikunja URL is required (e.g. https://vikunja.example.com).")
        if not params.username.strip():
            return ActionResult.error("Username is required.")
        if not params.password:
            return ActionResult.error("Password is required.")

        resp = await api_post(ctx, "/v1/connect", {
            "imperal_id": require_imperal_id(ctx),
            "base_url":   params.base_url.strip().rstrip("/"),
            "username":   params.username.strip(),
            "password":   params.password,
        })
        if resp.get("status") == "error":
            return ActionResult.error(_format_connect_error(resp, "Couldn't connect to Vikunja."))
        return ActionResult.success(
            data={
                "base_url":          resp.get("base_url"),
                "username":          resp.get("username"),
                "vikunja_user_id":   resp.get("vikunja_user_id"),
                "refresh_panels":    ["sidebar", "editor"],
            },
            summary=f"Connected to {resp.get('base_url')} as {resp.get('username')}.",
        )
    except Exception as e:
        log.error("connect_vikunja: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True)


@chat.function(
    "connect_vikunja_with_pat",
    action_type="write",
    chain_callable=True,
    effects=["create:connection"],
    event="connection.created",
    description=(
        "Advanced connect: user pastes a pre-existing Vikunja Personal "
        "Access Token (Settings → API tokens in their Vikunja UI). The "
        "PAT is encrypted on bridge and stored at rest."
    ),
    data_model=VikunjaConnectionResult,
)
async def connect_vikunja_with_pat(ctx, params: ConnectVikunjaWithPatParams) -> ActionResult:
    try:
        if not params.base_url.strip():
            return ActionResult.error("Vikunja URL is required.")
        if not params.pat.strip():
            return ActionResult.error("API token is required.")

        resp = await api_post(ctx, "/v1/connect/with-pat", {
            "imperal_id": require_imperal_id(ctx),
            "base_url":   params.base_url.strip().rstrip("/"),
            "pat":        params.pat.strip(),
        })
        if resp.get("status") == "error":
            return ActionResult.error(_format_connect_error(resp, "The token is not accepted by Vikunja."))
        return ActionResult.success(
            data={
                "base_url":        resp.get("base_url"),
                "username":        resp.get("username"),
                "vikunja_user_id": resp.get("vikunja_user_id"),
                "refresh_panels":  ["sidebar", "editor"],
            },
            summary=f"Connected to {resp.get('base_url')} as {resp.get('username')}.",
        )
    except Exception as e:
        log.error("connect_vikunja_with_pat: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True)


@chat.function(
    "disconnect_vikunja",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:connection"],
    event="connection.deleted",
    description=(
        "Disconnect from the user's Vikunja: revoke the stored API token "
        "in their instance and delete the local connection record."
    ),
    data_model=DisconnectResult,
)
async def disconnect_vikunja(ctx, params: NoParams) -> ActionResult:
    try:
        resp = await api_delete(ctx, "/v1/connect", {"imperal_id": require_imperal_id(ctx)})
        if resp.get("status") == "error":
            return ActionResult.error(_format_connect_error(resp, "Couldn't disconnect."))
        return ActionResult.success(
            data={"deleted": resp.get("deleted", True), "refresh_panels": ["sidebar", "editor"]},
            summary="Disconnected from Vikunja.",
        )
    except Exception as e:
        log.error("disconnect_vikunja: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True)


@chat.function(
    "get_connection_status",
    action_type="read",
    description=(
        "Check whether the user has a Vikunja connected (read-only — never "
        "echoes the API token). Returns connected: bool plus base_url and "
        "username when connected."
    ),
    data_model=ConnectionStatusResult,
)
async def get_connection_status(ctx, params: NoParams) -> ActionResult:
    try:
        resp = await api_get(ctx, "/v1/connection", {"imperal_id": require_imperal_id(ctx)})
        if isinstance(resp, dict) and resp.get("status") == "error":
            return ActionResult.error(_format_connect_error(resp, "Couldn't read connection status."))
        return ActionResult.success(
            data={
                "connected":       resp.get("connected", False),
                "base_url":        resp.get("base_url"),
                "username":        resp.get("username"),
                "vikunja_user_id": resp.get("vikunja_user_id"),
            },
            summary=(
                f"Connected to {resp.get('base_url')} as {resp.get('username')}."
                if resp.get("connected") else
                "No Vikunja connected. Connect one in the tasks panel."
            ),
        )
    except Exception as e:
        log.error("get_connection_status: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True)
