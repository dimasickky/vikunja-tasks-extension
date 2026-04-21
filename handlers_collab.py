"""tasks · Collaboration — comments and mentions."""
from __future__ import annotations

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_get, chat
from handlers_crud import _require_user


# ─── Params ────────────────────────────────────────────────────────────── #

class AddCommentParams(BaseModel):
    task_id: int
    comment: str = Field(..., min_length=1, description="Comment text (markdown supported).")


class MentionUserParams(BaseModel):
    task_id: int
    username: str = Field(
        ...,
        description="Vikunja username to mention (without @). Vikunja auto-links and notifies.",
    )
    message: str = Field(
        "",
        description="Optional context around the mention. If empty, plain '@username' is posted.",
    )


class ListCommentsParams(BaseModel):
    task_id: int


# ─── Impl ──────────────────────────────────────────────────────────────── #

async def _add_comment_impl(ctx, params: AddCommentParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        f"/v1/tasks/{params.task_id}/comments",
        {"imperal_id": imperal_id, "comment": params.comment},
    )
    if resp.get("status") == "error":
        return ActionResult.error(f"Не удалось добавить комментарий: {resp.get('detail')}")

    return ActionResult.success(
        message=f"Добавил комментарий в таск #{params.task_id}.",
        data={
            "comment_id": resp.get("id"),
            "task_id": params.task_id,
            "comment": resp.get("comment", params.comment),
        },
    )


async def _mention_user_impl(ctx, params: MentionUserParams) -> ActionResult:
    text = f"@{params.username}"
    if params.message:
        text = f"{params.message}\n\n{text}"

    result = await _add_comment_impl(
        ctx, AddCommentParams(task_id=params.task_id, comment=text),
    )
    # Replay as "mention" event topic for automation distinction
    if hasattr(result, "data") and result.data:
        result.data["mentioned_username"] = params.username
    return result


async def _list_comments_impl(ctx, params: ListCommentsParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(
        f"/v1/tasks/{params.task_id}/comments", {"imperal_id": imperal_id},
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(f"Не удалось получить комменты: {resp.get('detail')}")

    comments = resp if isinstance(resp, list) else []
    return ActionResult.success(
        message=f"{len(comments)} комментариев в таске #{params.task_id}.",
        data={
            "count": len(comments),
            "comments": [
                {
                    "comment_id": c["id"],
                    "comment": c.get("comment", ""),
                    "author": c.get("author", {}).get("username", ""),
                    "created": c.get("created"),
                }
                for c in comments
            ],
        },
    )


# ─── @chat.function wrappers ───────────────────────────────────────────── #

@chat.function(
    "add_comment",
    action_type="write",
    event="task.commented",
    description="Add a comment to a task (markdown supported).",
)
async def add_comment(ctx, params: AddCommentParams) -> ActionResult:
    return await _add_comment_impl(ctx, params)


@chat.function(
    "mention_user",
    action_type="write",
    event="task.mentioned",
    description=(
        "Mention a user in a task comment. Vikunja auto-links '@username' and notifies. "
        "Use when user wants to notify/loop in someone."
    ),
)
async def mention_user(ctx, params: MentionUserParams) -> ActionResult:
    return await _mention_user_impl(ctx, params)


@chat.function(
    "list_comments",
    action_type="read",
    description="List all comments on a task.",
)
async def list_comments(ctx, params: ListCommentsParams) -> ActionResult:
    return await _list_comments_impl(ctx, params)
