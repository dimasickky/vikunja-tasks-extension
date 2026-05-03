"""tasks · Collaboration — comments and mentions."""
from __future__ import annotations

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult

from app import api_post, api_get, api_delete, chat, is_no_connection_error
from handlers_crud import _require_user, _bridge_error_msg


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


class UpdateCommentParams(BaseModel):
    task_id: int
    comment_id: int
    comment: str = Field(..., min_length=1, description="New comment text (markdown supported).")


class DeleteCommentParams(BaseModel):
    task_id: int
    comment_id: int


async def _add_comment_impl(ctx, params: AddCommentParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}/comments",
                          {"imperal_id": imperal_id, "comment": params.comment})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't add comment"))

    return ActionResult.success(
        summary=f"Comment added to task #{params.task_id}.",
        data={
            "comment_id": resp.get("id"),
            "task_id":    params.task_id,
            "comment":    resp.get("comment", params.comment),
        },
    )


async def _mention_user_impl(ctx, params: MentionUserParams) -> ActionResult:
    text = f"@{params.username}"
    if params.message:
        text = f"{params.message}\n\n{text}"

    result = await _add_comment_impl(ctx, AddCommentParams(task_id=params.task_id, comment=text))
    if hasattr(result, "data") and result.data:
        result.data["mentioned_username"] = params.username
    return result


@chat.function(
    "add_comment",
    action_type="write",
    chain_callable=True,
    effects=["create:comment"],
    event="task.commented",
    description="Add a comment to a task (markdown supported).",
)
async def add_comment(ctx, params: AddCommentParams) -> ActionResult:
    return await _add_comment_impl(ctx, params)


@chat.function(
    "mention_user",
    action_type="write",
    chain_callable=True,
    effects=["create:comment"],
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
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, f"/v1/tasks/{params.task_id}/comments", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch comments"))

    comments = resp if isinstance(resp, list) else []
    return ActionResult.success(
        summary=f"{len(comments)} comment(s) on task #{params.task_id}.",
        data={
            "count":    len(comments),
            "comments": [
                {
                    "comment_id": c["id"],
                    "comment":    c.get("comment", ""),
                    "author":     c.get("author", {}).get("username", ""),
                    "created":    c.get("created"),
                }
                for c in comments
            ],
        },
    )


@chat.function(
    "update_comment",
    action_type="write",
    chain_callable=True,
    effects=["update:comment"],
    event="task.comment_updated",
    description="Edit the text of an existing comment on a task.",
)
async def update_comment(ctx, params: UpdateCommentParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(
        ctx,
        f"/v1/tasks/{params.task_id}/comments/{params.comment_id}",
        {"imperal_id": imperal_id, "comment": params.comment},
    )
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update comment"))

    return ActionResult.success(
        summary=f"Comment #{params.comment_id} on task #{params.task_id} updated.",
        data={"comment_id": params.comment_id, "task_id": params.task_id},
    )


@chat.function(
    "delete_comment",
    action_type="destructive",
    chain_callable=True,
    effects=["delete:comment"],
    event="task.comment_deleted",
    description="Permanently delete a comment from a task. Cannot be undone.",
)
async def delete_comment(ctx, params: DeleteCommentParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        ctx,
        f"/v1/tasks/{params.task_id}/comments/{params.comment_id}",
        {"imperal_id": imperal_id},
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete comment"))

    return ActionResult.success(
        summary=f"Comment #{params.comment_id} deleted from task #{params.task_id}.",
        data={"comment_id": params.comment_id, "task_id": params.task_id},
    )
