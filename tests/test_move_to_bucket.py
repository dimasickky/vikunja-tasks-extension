"""tasks · move_to_bucket / move_tasks_to_bucket (kanban board-move fix).

Regression guard for the bug found 2026-08-16 and reported by a user
("move_to_bucket / move to bucket say success but do nothing"): `bucket_id`
on Vikunja's regular task-update endpoint (POST /tasks/{id}) is a virtual
response field — Vikunja echoes it back with HTTP 200 but never writes to
the underlying `task_buckets` join table (keyed per project_view_id). This
extension used to move tasks via that endpoint through `_update_task_impl`,
so every "move" silently no-op'd while reporting success.

The fix routes both the single-task and batch move functions through
`_move_task_to_bucket_impl`, which calls the bridge's dedicated
`.../views/{view_id}/buckets/{bucket_id}/tasks` endpoint instead. These
tests deliberately do NOT mock the old `/tasks/{id}` POST path for bucket
moves — if the code regresses to calling it, MockHTTP returns its default
404 "No mock registered" body, the handler treats that as a bridge error,
and the test fails loudly instead of silently no-op'ing again.
"""
from imperal_sdk.testing import MockContext

import handlers_organize as ho
from handlers_organize import MoveToBucketParams, MoveTasksToBucketParams


BRIDGE = "https://bridge.test"


def _views_url(project_id: int) -> str:
    return f"{BRIDGE}/v1/projects/{project_id}/views"


def _bucket_tasks_url(project_id: int, view_id: int, bucket_id: int) -> str:
    return f"{BRIDGE}/v1/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks"


def _task_url(task_id: int) -> str:
    return f"{BRIDGE}/v1/tasks/{task_id}"


async def test_move_to_bucket_uses_dedicated_bucket_endpoint():
    """Single-task move must hit the bucket-tasks route, not /tasks/{id}."""
    ctx = MockContext()

    # MockHTTP._find returns the FIRST registered mock matching a URL pattern,
    # for every call — it can't be told "answer differently the 2nd time". This
    # handler hits GET /tasks/{id} twice (pre-move project_id lookup, then the
    # post-move re-fetch for full_result), so one full response covers both.
    ctx.http.mock_get(_task_url(42), {
        "id": 42, "project_id": 3, "title": "Ship it", "done": False,
        "due_date": None, "priority": 2, "percent_done": 0.0,
    })
    ctx.http.mock_get(_views_url(3), [{"id": 7, "view_kind": "kanban"}])
    ctx.http.mock_post(_bucket_tasks_url(3, 7, 5), {"task_id": 42, "bucket_id": 5})

    result = await ho.move_to_bucket(ctx, MoveToBucketParams(task_id=42, bucket_id=5))

    assert result.status == "success"
    assert result.data["task_id"] == 42
    assert result.data["title"] == "Ship it"
    assert result.data["priority"] == 2
    assert "refresh_panels" in result.data


async def test_move_to_bucket_reports_bridge_error_not_fake_success():
    """If the bucket endpoint 404s (e.g. old code hitting the wrong path),
    this must surface as an error — never as a false 'success'."""
    ctx = MockContext()

    ctx.http.mock_get(_task_url(99), {"id": 99, "project_id": 3, "title": "X"})
    ctx.http.mock_get(_views_url(3), [{"id": 7, "view_kind": "kanban"}])
    # Deliberately NOT mocking the bucket-tasks POST route.

    result = await ho.move_to_bucket(ctx, MoveToBucketParams(task_id=99, bucket_id=5))

    assert result.status == "error"


async def test_move_tasks_to_bucket_batch_uses_dedicated_endpoint():
    """Batch move: bucket resolved once, each task goes through the real
    bucket-tasks route, and full task objects are NOT re-fetched per item."""
    ctx = MockContext()

    ctx.http.mock_get(_views_url(3), [{"id": 7, "view_kind": "kanban"}])
    ctx.http.mock_post(_bucket_tasks_url(3, 7, 5), {"ok": True})

    result = await ho.move_tasks_to_bucket(
        ctx, MoveTasksToBucketParams(task_ids=[10, 11, 12], bucket_id=5, project_id=3)
    )

    assert result.status == "success"
    assert result.data["succeeded_count"] == 3
    assert result.data["failed_count"] == 0
    assert all(r["ok"] for r in result.data["results"])


async def test_move_tasks_to_bucket_partial_failure_reported_per_task():
    ctx = MockContext()

    ctx.http.mock_get(_views_url(3), [{"id": 7, "view_kind": "kanban"}])
    # Only bucket 5 is mocked — a move to a different bucket_id would 404,
    # but here we simulate one task simply not resolving to a valid id.

    ctx.http.mock_post(_bucket_tasks_url(3, 7, 5), {"ok": True})

    result = await ho.move_tasks_to_bucket(
        ctx, MoveTasksToBucketParams(task_ids=[20], task_titles=["Nonexistent task xyz"],
                                      bucket_id=5, project_id=3)
    )

    assert result.data["succeeded_count"] == 1
    assert result.data["failed_count"] == 1
    failed = [r for r in result.data["results"] if not r["ok"]][0]
    assert failed["error"] == "task not found"
