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

import logging

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from imperal_sdk.chat import ActionResult

from app import api_get, api_post, api_delete, api_upload, chat
from handlers_crud import _require_user, _bridge_error_msg
from models_return import UploadTaskAttachmentResult, ListTaskAttachmentsResult, DeleteTaskAttachmentResult
from error_codes import TASKS_BRIDGE_ERROR, TASKS_ATTACHMENT_NOT_FOUND, TASKS_ATTACHMENT_TOO_LARGE

log = logging.getLogger("tasks")

_MODEL_CONFIG = ConfigDict(populate_by_name=True)


def _extract_b64(payload) -> tuple[str, str, str]:
    """Return (data_base64, filename, content_type) from a FileUpload payload.

    Same shape/parsing as notes/handlers_attachments.py._extract_b64 — the
    panel sends a list[dict] (or a single dict) with data_base64/name/
    content_type; a data: URI prefix is stripped if present.
    """
    if isinstance(payload, list) and payload:
        item = payload[0] if isinstance(payload[0], dict) else {}
    elif isinstance(payload, dict):
        item = payload
    else:
        return "", "", ""
    b64 = item.get("data_base64", "")
    if b64.startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]
    return b64, item.get("name", "file"), item.get("content_type", "application/octet-stream")


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
    """Upload a file attachment to a task via the panel's FileUpload payload."""
    imperal_id = _require_user(ctx)
    if isinstance(imperal_id, ActionResult):
        return imperal_id

    data_b64, filename, content_type = _extract_b64(params.files)
    if not data_b64:
        return ActionResult.error("No file provided. Attach a file from the panel first.", code=TASKS_BRIDGE_ERROR)

    import base64
    try:
        data = base64.b64decode(data_b64)
    except Exception:
        return ActionResult.error("Uploaded file payload is not valid base64.", code=TASKS_BRIDGE_ERROR)

    if len(data) > 20 * 1024 * 1024:
        return ActionResult.error(
            f"'{filename}' is larger than Vikunja's 20MB attachment limit.",
            code=TASKS_ATTACHMENT_TOO_LARGE,
        )

    resp = await api_upload(
        ctx, f"/v1/tasks/{params.task_id}/attachments", {"imperal_id": imperal_id},
        filename, data, content_type,
    )
    if isinstance(resp, dict) and resp.get("status") == "error":
        return ActionResult.error(_bridge_error_msg(resp, "Couldn't upload attachment"), code=TASKS_BRIDGE_ERROR)

    # Vikunja's own response shape is {"success": [TaskAttachment...], "errors": [...]}
    # (pkg/routes/api/v1/task_attachment.go) — NOT a flat attachment list.
    raw_success = resp.get("success") if isinstance(resp, dict) else None
    raw_errors = resp.get("errors") if isinstance(resp, dict) else None
    uploaded = [_attachment_item(a) for a in (raw_success or [])]

    if not uploaded:
        detail = ""
        if raw_errors:
            detail = f" ({raw_errors[0].get('message', '')})"
        return ActionResult.error(
            f"Vikunja rejected '{filename}'{detail}.", code=TASKS_BRIDGE_ERROR,
        )

    return ActionResult.success(
        summary=f"Uploaded '{filename}' to task #{params.task_id}.",
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
