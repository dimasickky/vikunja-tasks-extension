"""tasks · Collaboration — comments and mentions."""

import asyncio
from typing import List, Optional

from pydantic import BaseModel, Field

from imperal_sdk.chat import ActionResult
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD

from app import api_post, api_get, api_delete, chat
from handlers_crud import _require_user, _bridge_error_msg, _check_batch_size, _BULK_CONCURRENCY
from models_return import (
    CommentResult,
    MentionCommentResult,
    ListCommentsResult,
    CommentRefResult,
    BulkCommentItem,
    BulkCommentResult,
)
from error_codes import TASKS_BRIDGE_ERROR, TASKS_TASK_NOT_FOUND, TASKS_TASK_AMBIGUOUS


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


class DeleteCommentsParams(BaseModel):
    task_id: int = Field(
        0,
        description="Integer task ID. Pass 0 when you only know the task by name.",
    )
    task_name: Optional[str] = Field(
        None,
        description="Task title to search for when task_id is unknown. Auto-resolved.",
    )
    bucket_name: Optional[str] = Field(
        None,
        description="Bucket/column name to disambiguate when multiple tasks share the same title.",
    )
    comment_ids: Optional[List[int]] = Field(
        None,
        description=(
            "Specific comment IDs to delete. Omit (or pass an empty list) to delete "
            "EVERY comment on the task — use for 'delete all comments on task X'."
        ),
    )


class AddCommentsParams(BaseModel):
    task_id: int = Field(
        0,
        description="Integer task ID. Pass 0 when you only know the task by name.",
    )
    task_name: Optional[str] = Field(
        None,
        description="Task title to search for when task_id is unknown. Auto-resolved.",
    )
    bucket_name: Optional[str] = Field(
        None,
        description="Bucket/column name to disambiguate when multiple tasks share the same title.",
    )
    comments: List[str] = Field(
        ...,
        min_length=1,
        description="Comment texts to post, one call each, in this order (markdown supported).",
    )


async def _resolve_task_id_by_name(
    ctx, imperal_id: str, task_name: str, bucket_name: Optional[str],
) -> tuple[Optional[int], Optional[ActionResult]]:
    """Same resolution used by assign_task: search by title, narrow by bucket,
    refuse silently on 0 or >1 matches rather than guessing which task to hit."""
    from handlers_organize import _filter_tasks_by_bucket  # local import: avoids a hard circular dep at module load

    search_resp = await api_get(ctx, "/v1/tasks/all", {
        "imperal_id": imperal_id, "s": task_name, "per_page": 20,
    })
    tasks = search_resp if isinstance(search_resp, list) else []
    if not tasks:
        return None, ActionResult.error(
            f"Task '{task_name}' not found. Check the spelling or call list_my_tasks() to browse.",
            code=TASKS_TASK_NOT_FOUND,
        )
    if len(tasks) > 1 and bucket_name:
        tasks = await _filter_tasks_by_bucket(ctx, imperal_id, tasks, bucket_name)
    if len(tasks) > 1:
        matches = ", ".join(f"#{t['id']} '{t.get('title', '?')}'" for t in tasks[:5])
        return None, ActionResult.error(
            f"Multiple tasks match '{task_name}': {matches}. "
            "Pass bucket_name to narrow down, or pass task_id directly.",
            code=TASKS_TASK_AMBIGUOUS,
        )
    return tasks[0]["id"], None


async def _add_comment_impl(ctx, params: AddCommentParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_post(ctx, f"/v1/tasks/{params.task_id}/comments",
                          {"imperal_id": imperal_id, "comment": params.comment})
    if resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't add comment"), code=TASKS_BRIDGE_ERROR)

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
    id_projection="task_id",
    effects=["create:comment"],
    event="task.commented",
    description="Add a comment to a task (markdown supported).",
    data_model=CommentResult,
)
async def add_comment(ctx, params: AddCommentParams) -> ActionResult:
    return await _add_comment_impl(ctx, params)


@chat.function(
    "mention_user",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["create:comment"],
    event="task.mentioned",
    description=(
        "Mention a user in a task comment. Vikunja auto-links '@username' and notifies. "
        "Use when user wants to notify/loop in someone."
    ),
    data_model=MentionCommentResult,
)
async def mention_user(ctx, params: MentionUserParams) -> ActionResult:
    return await _mention_user_impl(ctx, params)


@chat.function(
    "list_comments",
    action_type="read",
    description="List all comments on a task.",
    data_model=ListCommentsResult,
)
async def list_comments(ctx, params: ListCommentsParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, f"/v1/tasks/{params.task_id}/comments", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't fetch comments"), code=TASKS_BRIDGE_ERROR)

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
    id_projection="task_id",
    effects=["update:comment"],
    event="task.comment_updated",
    description="Edit the text of an existing comment on a task.",
    data_model=CommentRefResult,
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't update comment"), code=TASKS_BRIDGE_ERROR)

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
    data_model=CommentRefResult,
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
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete comment"), code=TASKS_BRIDGE_ERROR)

    return ActionResult.success(
        summary=f"Comment #{params.comment_id} deleted from task #{params.task_id}.",
        data={"comment_id": params.comment_id, "task_id": params.task_id},
    )


async def _run_comment_batch(ctx, sem: asyncio.Semaphore, task_id: int, items: list, verb: str, op) -> List[BulkCommentItem]:
    """Fan out `op(item)` over `items` under `sem`, one row per item, never
    aborting the whole batch on a single failure — same shape as
    handlers_crud.py's task batches, just scoped to one task's comments."""
    total = len(items)
    done = 0

    async def _one(item) -> BulkCommentItem:
        nonlocal done
        async with sem:
            row = await op(item)
        done += 1
        if total > 1:
            try:
                await ctx.progress(min(0.95, done / total), f"{verb.capitalize()} {done} of {total}…")
            except Exception:
                pass
        return row

    return list(await asyncio.gather(*[_one(item) for item in items]))


@chat.function(
    "delete_comments",
    action_type="destructive",
    chain_callable=True,
    id_projection="task_id",
    effects=["delete:comment"],
    event="task.comments_deleted",
    description=(
        "Delete MULTIPLE comments on a task at once. Pass comment_ids to delete specific ones, "
        "or omit comment_ids entirely to delete EVERY comment on the task. Pass task_id, or "
        "task_name (+ optional bucket_name to disambiguate) to resolve it by title. "
        "Use when the user asks to delete 2+ comments, or 'delete all comments on task X'."
    ),
    data_model=BulkCommentResult,
)
async def delete_comments(ctx, params: DeleteCommentsParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    task_id = params.task_id
    if task_id == 0 and params.task_name:
        task_id, err = await _resolve_task_id_by_name(ctx, imperal_id, params.task_name, params.bucket_name)
        if err is not None:
            return err
    if not task_id:
        return ActionResult.error(
            "task_id is required. Pass task_name to let delete_comments auto-resolve by title.",
            code=VALIDATION_MISSING_FIELD,
        )

    comment_ids = params.comment_ids
    if not comment_ids:
        # "Delete all": list the task's own comments first — there is no bulk
        # delete-everything route on Vikunja's side, so this is the only way
        # to know what "all" means before fanning the deletes out.
        list_resp = await api_get(ctx, f"/v1/tasks/{task_id}/comments", {"imperal_id": imperal_id})
        if isinstance(list_resp, dict) and list_resp.get("status") == "error":
            return ActionResult.error(_bridge_error_msg(list_resp, "Couldn't fetch comments"), code=TASKS_BRIDGE_ERROR)
        comments = list_resp if isinstance(list_resp, list) else []
        comment_ids = [c["id"] for c in comments]

    if not comment_ids:
        return ActionResult.success(
            summary=f"Task #{task_id} has no comments to delete.",
            data={"succeeded_count": 0, "failed_count": 0, "results": [], "refresh_panels": ["editor"]},
        )

    oversized = _check_batch_size(comment_ids, "comments")
    if oversized is not None:
        return oversized

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _delete_one(comment_id: int) -> BulkCommentItem:
        resp = await api_delete(ctx, f"/v1/tasks/{task_id}/comments/{comment_id}", {"imperal_id": imperal_id})
        if isinstance(resp, dict) and resp.get("status") == "error":
            return BulkCommentItem(comment_id=comment_id, task_id=task_id, ok=False,
                                    error=_bridge_error_msg(resp, "delete failed"))
        return BulkCommentItem(comment_id=comment_id, task_id=task_id, ok=True)

    results = await _run_comment_batch(ctx, sem, task_id, comment_ids, "deleted", _delete_one)
    succeeded = sum(1 for r in results if r.ok)
    failed = len(results) - succeeded

    return ActionResult.success(
        summary=f"Deleted {succeeded}/{len(results)} comment(s) on task #{task_id}"
                + (f" ({failed} failed)." if failed else "."),
        data={
            "succeeded_count": succeeded,
            "failed_count": failed,
            "results": [r.model_dump() for r in results],
            "refresh_panels": ["editor"],
        },
    )


@chat.function(
    "add_comments",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["create:comment"],
    event="task.comments_added",
    description=(
        "Add MULTIPLE comments to a task at once, in order. Pass task_id, or task_name "
        "(+ optional bucket_name to disambiguate) to resolve it by title. "
        "Use when the user asks to post 2+ comments in one request, e.g. a simulated work log."
    ),
    data_model=BulkCommentResult,
)
async def add_comments(ctx, params: AddCommentsParams) -> ActionResult:
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    task_id = params.task_id
    if task_id == 0 and params.task_name:
        task_id, err = await _resolve_task_id_by_name(ctx, imperal_id, params.task_name, params.bucket_name)
        if err is not None:
            return err
    if not task_id:
        return ActionResult.error(
            "task_id is required. Pass task_name to let add_comments auto-resolve by title.",
            code=VALIDATION_MISSING_FIELD,
        )

    oversized = _check_batch_size(params.comments, "comments")
    if oversized is not None:
        return oversized

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _add_one(text: str) -> BulkCommentItem:
        resp = await api_post(ctx, f"/v1/tasks/{task_id}/comments", {"imperal_id": imperal_id, "comment": text})
        if isinstance(resp, dict) and resp.get("status") == "error":
            return BulkCommentItem(comment_id=None, task_id=task_id, ok=False,
                                    error=_bridge_error_msg(resp, "add failed"))
        return BulkCommentItem(comment_id=resp.get("id"), task_id=task_id, ok=True)

    results = await _run_comment_batch(ctx, sem, task_id, params.comments, "posted", _add_one)
    succeeded = sum(1 for r in results if r.ok)
    failed = len(results) - succeeded

    return ActionResult.success(
        summary=f"Added {succeeded}/{len(results)} comment(s) to task #{task_id}"
                + (f" ({failed} failed)." if failed else "."),
        data={
            "succeeded_count": succeeded,
            "failed_count": failed,
            "results": [r.model_dump() for r in results],
            "refresh_panels": ["editor"],
        },
    )
