"""tasks · Task attachment handlers (upload / list / delete).

Vikunja itself stores the files (task_attachments_enabled=true, 20MB cap per
/api/v1/info) — these handlers are a thin pass-through to the bridge's
routes_attachments.py, which streams bytes straight to the user's own
Vikunja instance. No file bytes are ever persisted by this extension or by
vikunja-bridge; mirrors the notes extension's upload_attachment/
delete_attachment pattern (handlers_attachments.py there), adapted for
Vikunja's `files` (plural) multipart field name and its numeric
attachment IDs instead of notes' UUIDs.

Download is intentionally NOT exposed as a chat.function — binary content
doesn't round-trip through a chat response usefully (same reasoning notes
applied: no download_attachment there either). Users open attachments from
Vikunja's own UI or a future panel link.
"""

import asyncio
import logging
from typing import List

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, api_upload, chat
from handlers_crud import _require_user, _bridge_error_msg, _check_batch_size, _BULK_CONCURRENCY
from models_return import (
    UploadTaskAttachmentResult, ListTaskAttachmentsResult, DeleteTaskAttachmentResult,
    DeleteTaskAttachmentsResult,
)
from error_codes import TASKS_BRIDGE_ERROR, TASKS_ATTACHMENT_NOT_FOUND, TASKS_ATTACHMENT_TOO_LARGE

log = logging.getLogger("tasks")

_MODEL_CONFIG = ConfigDict(populate_by_name=True)


def _extract_files(payload) -> list[tuple[str, str, str]]:
    """Return [(data_base64, filename, content_type), ...] from a FileUpload
    payload.

    Same shape/parsing as notes/handlers_attachments.py._extract_files — the
    panel's ui.FileUpload(multiple=True) sends a list[dict], one entry per
    file selected, each with data_base64/name/content_type; a data: URI
    prefix is stripped if present. A single dict (older callers / single-file
    forms) is wrapped as a one-item list. Previously only payload[0] was ever
    read here, so selecting 3 files in the panel silently uploaded 1 — this
    now walks the whole list.
    """
    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = [p for p in payload if isinstance(p, dict)]
    else:
        return []

    out = []
    for item in items:
        b64 = item.get("data_base64", "")
        if not b64:
            continue
        if b64.startswith("data:") and "," in b64:
            b64 = b64.split(",", 1)[1]
        out.append((b64, item.get("name", "file"), item.get("content_type", "application/octet-stream")))
    return out


class UploadTaskAttachmentParams(BaseModel):
    model_config = _MODEL_CONFIG

    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    files: object = Field(
        default=None,
        description="FileUpload payload (list[dict] with data_base64/name/content_type)",
        validation_alias=AliasChoices("files", "file", "upload"),
    )


class ListTaskAttachmentsParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")


class DeleteTaskAttachmentParams(BaseModel):
    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    attachment_id: int = Field(..., description="Integer attachment ID from list_task_attachments.")


def _attachment_item(raw: dict) -> dict:
    file_info = raw.get("file") or {}
    return {
        "attachment_id": raw.get("id"),
        "task_id": raw.get("task_id"),
        "filename": file_info.get("name", ""),
        "size": file_info.get("size"),
        "created": raw.get("created"),
    }


@chat.function(
    "upload_task_attachment",
    action_type="write",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.attachment_uploaded",
    description=(
        "Attach a file (photo, PDF, doc) to a task. Vikunja stores the file itself "
        "(max 20MB). Use when the user wants to attach/upload a photo or file to a task."
    ),
    data_model=UploadTaskAttachmentResult,
)
async def upload_task_attachment(ctx, params: UploadTaskAttachmentParams) -> ActionResult:
    """Upload one or more file attachments to a task via the panel's FileUpload payload."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    files = _extract_files(params.files)
    if not files:
        return ActionResult.error("No file provided. Attach a file from the panel first.", code=TASKS_BRIDGE_ERROR)

    import base64

    uploaded: list[dict] = []
    failed: list[str] = []

    for data_b64, filename, content_type in files:
        try:
            data = base64.b64decode(data_b64)
        except Exception:
            failed.append(f"{filename} (invalid base64)")
            continue

        if len(data) > 20 * 1024 * 1024:
            failed.append(f"{filename} (over Vikunja's 20MB limit)")
            continue

        resp = await api_upload(
            ctx, f"/v1/tasks/{params.task_id}/attachments", {"imperal_id": imperal_id},
            filename, data, content_type,
        )
        if isinstance(resp, dict) and resp.get("status") == "error":
            failed.append(f"{filename} ({_bridge_error_msg(resp, 'upload failed')})")
            continue

        # Vikunja's own response shape is {"success": [TaskAttachment...], "errors": [...]}
        # (pkg/routes/api/v1/task_attachment.go) — NOT a flat attachment list.
        raw_success = resp.get("success") if isinstance(resp, dict) else None
        raw_errors = resp.get("errors") if isinstance(resp, dict) else None
        item_uploaded = [_attachment_item(a) for a in (raw_success or [])]

        if not item_uploaded:
            detail = f" ({raw_errors[0].get('message', '')})" if raw_errors else ""
            failed.append(f"{filename}{detail}")
            continue

        uploaded.extend(item_uploaded)

    if not uploaded:
        return ActionResult.error(
            f"Vikunja rejected all {len(files)} file(s): {'; '.join(failed)}.", code=TASKS_BRIDGE_ERROR,
        )

    if failed:
        summary = (
            f"Uploaded {len(uploaded)} of {len(files)} file(s) to task #{params.task_id} "
            f"— {len(failed)} failed: {'; '.join(failed)}"
        )
    else:
        names = ", ".join(a["filename"] for a in uploaded)
        summary = f"Uploaded {names} to task #{params.task_id}."

    return ActionResult.success(
        summary=summary,
        data={"task_id": params.task_id, "uploaded": uploaded, "refresh_panels": ["sidebar", "editor"]},
    )


@chat.function(
    "list_task_attachments",
    action_type="read",
    chain_callable=True,
    effects=[],
    description="List all attachments (files/photos) on a task.",
    data_model=ListTaskAttachmentsResult,
)
async def list_task_attachments(ctx, params: ListTaskAttachmentsParams) -> ActionResult:
    """List attachments on a task."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_get(ctx, f"/v1/tasks/{params.task_id}/attachments", {"imperal_id": imperal_id})
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't list attachments"), code=TASKS_BRIDGE_ERROR)

    raw_items = resp if isinstance(resp, list) else []
    items = [_attachment_item(a) for a in raw_items]
    if not items:
        return ActionResult.success(
            summary=f"No attachments on task #{params.task_id}.",
            data={"task_id": params.task_id, "count": 0, "attachments": []},
        )

    lines = "\n".join(f"• {a['filename']} (ID: {a['attachment_id']})" for a in items)
    return ActionResult.success(
        summary=f"{len(items)} attachment(s) on task #{params.task_id}:\n{lines}",
        data={"task_id": params.task_id, "count": len(items), "attachments": items},
    )


@chat.function(
    "delete_task_attachment",
    action_type="destructive",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.attachment_deleted",
    description="Remove a file attachment from a task. Cannot be undone.",
    data_model=DeleteTaskAttachmentResult,
)
async def delete_task_attachment(ctx, params: DeleteTaskAttachmentParams) -> ActionResult:
    """Delete an attachment from a task."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    resp = await api_delete(
        ctx, f"/v1/tasks/{params.task_id}/attachments/{params.attachment_id}",
        params={"imperal_id": imperal_id},
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        code = TASKS_ATTACHMENT_NOT_FOUND if resp.get("http_status") == 404 else TASKS_BRIDGE_ERROR
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't delete attachment"), code=code)

    return ActionResult.success(
        summary=f"Deleted attachment #{params.attachment_id} from task #{params.task_id}.",
        data={"task_id": params.task_id, "attachment_id": params.attachment_id,
              "deleted": True, "refresh_panels": ["sidebar", "editor"]},
    )


class DeleteTaskAttachmentsParams(BaseModel):
    model_config = _MODEL_CONFIG

    task_id: int = Field(..., description="Integer task ID. Never UUID.")
    attachment_ids: List[int] = Field(
        ..., description="List of integer attachment IDs to delete — from list_task_attachments.",
    )


@chat.function(
    "delete_task_attachments",
    action_type="destructive",
    chain_callable=True,
    id_projection="task_id",
    effects=["update:task"],
    event="task.attachments_deleted",
    description=(
        "Remove SEVERAL file attachments from a task at once. Pass task_id and "
        "attachment_ids (list of integers from list_task_attachments). Use when the user "
        "wants to remove 2+ attachments in one request. Cannot be undone."
    ),
    data_model=DeleteTaskAttachmentsResult,
)
async def delete_task_attachments(ctx, params: DeleteTaskAttachmentsParams) -> ActionResult:
    """Delete a set of attachments from one task, reported per attachment.

    Same reasoning as tasks' other bulk tools (see handlers_crud.py
    _run_task_batch): a bounded, concurrent fan-out with one row per item, so
    a partial failure among several deletes is visible rather than silently
    swallowed. There is no bulk-delete endpoint on Vikunja's own API for
    attachments, so this issues one DELETE per id.
    """
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    oversized = _check_batch_size(params.attachment_ids, "attachments")
    if oversized:
        return oversized

    sem = asyncio.Semaphore(_BULK_CONCURRENCY)

    async def _delete_one(att_id: int) -> dict:
        async with sem:
            resp = await api_delete(
                ctx, f"/v1/tasks/{params.task_id}/attachments/{att_id}",
                params={"imperal_id": imperal_id},
            )
        if isinstance(resp, dict) and resp.get("status") == "error":
            return {"attachment_id": att_id, "deleted": False,
                     "error": _bridge_error_msg(resp, "Delete failed")}
        return {"attachment_id": att_id, "deleted": True}

    results = await asyncio.gather(*(_delete_one(a) for a in params.attachment_ids))
    results = list(results)

    deleted_count = sum(1 for r in results if r["deleted"])
    failed_count = len(results) - deleted_count
    summary = f"Deleted {deleted_count} attachment(s) from task #{params.task_id}."
    if failed_count:
        summary += f" {failed_count} failed."

    return ActionResult.success(
        summary=summary,
        data={
            "task_id": params.task_id,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "results": results,
            "refresh_panels": ["sidebar", "editor"],
        },
    )
