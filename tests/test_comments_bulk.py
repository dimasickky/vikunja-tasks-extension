"""tasks · delete_comments / add_comments (bulk comment operations).

Vikunja has no bulk comment endpoint on either side (bridge or upstream) —
comments are always single add/delete calls. These two tools fan out over
the extension's own existing batch machinery (_check_batch_size +
_BULK_CONCURRENCY semaphore from handlers_crud.py), the same pattern already
proven by delete_tasks/complete_tasks/move_tasks_to_bucket. `delete_comments`
additionally supports "delete ALL comments on a task" by omitting
comment_ids — it lists the task's comments itself first, since there is no
bridge endpoint that means "all" on its own.
"""
from imperal_sdk.testing import MockContext

import app as _app
import handlers_collab as hc
from handlers_collab import AddCommentsParams, DeleteCommentsParams


BRIDGE = _app._bridge_url()


def _comments_url(task_id: int) -> str:
    return f"{BRIDGE}/v1/tasks/{task_id}/comments"


def _comment_url(task_id: int, comment_id: int) -> str:
    return f"{BRIDGE}/v1/tasks/{task_id}/comments/{comment_id}"


async def test_delete_comments_with_explicit_ids():
    ctx = MockContext()
    for cid in (1, 2, 3):
        ctx.http._mocks.append(("DELETE", _comment_url(42, cid), {"id": cid}, 200, {}))

    result = await hc.delete_comments(ctx, DeleteCommentsParams(task_id=42, comment_ids=[1, 2, 3]))

    assert result.status == "success"
    assert result.data["succeeded_count"] == 3
    assert result.data["failed_count"] == 0
    assert {r["comment_id"] for r in result.data["results"]} == {1, 2, 3}


async def test_delete_comments_all_when_ids_omitted():
    """Omitting comment_ids must delete EVERY comment currently on the task."""
    ctx = MockContext()
    ctx.http.mock_get(_comments_url(42), [
        {"id": 10, "comment": "a"}, {"id": 11, "comment": "b"}, {"id": 12, "comment": "c"},
    ])
    for cid in (10, 11, 12):
        ctx.http._mocks.append(("DELETE", _comment_url(42, cid), {"id": cid}, 200, {}))

    result = await hc.delete_comments(ctx, DeleteCommentsParams(task_id=42))

    assert result.status == "success"
    assert result.data["succeeded_count"] == 3
    assert {r["comment_id"] for r in result.data["results"]} == {10, 11, 12}


async def test_delete_comments_all_on_task_with_no_comments_is_a_noop_success():
    ctx = MockContext()
    ctx.http.mock_get(_comments_url(42), [])

    result = await hc.delete_comments(ctx, DeleteCommentsParams(task_id=42))

    assert result.status == "success"
    assert result.data["succeeded_count"] == 0
    assert result.data["results"] == []


async def test_delete_comments_resolves_task_by_name():
    ctx = MockContext()
    ctx.http.mock_get(f"{BRIDGE}/v1/tasks/all", [{"id": 42, "title": "Ship it"}])
    ctx.http.mock_get(_comments_url(42), [{"id": 5, "comment": "x"}])
    ctx.http._mocks.append(("DELETE", _comment_url(42, 5), {"id": 5}, 200, {}))

    result = await hc.delete_comments(ctx, DeleteCommentsParams(task_name="Ship it"))

    assert result.status == "success"
    assert result.data["succeeded_count"] == 1


async def test_delete_comments_partial_failure_reported_per_item():
    ctx = MockContext()
    ctx.http._mocks.append(("DELETE", _comment_url(42, 1), {"id": 1}, 200, {}))
    ctx.http._mocks.append(("DELETE", _comment_url(42, 2), {"status": "error", "detail": "not found"}, 404, {}))

    result = await hc.delete_comments(ctx, DeleteCommentsParams(task_id=42, comment_ids=[1, 2]))

    assert result.status == "success"  # partial success still reports as success at the batch level
    assert result.data["succeeded_count"] == 1
    assert result.data["failed_count"] == 1
    failed = [r for r in result.data["results"] if not r["ok"]]
    assert failed and failed[0]["comment_id"] == 2


async def test_add_comments_posts_each_in_order():
    ctx = MockContext()
    ctx.http.mock_post(_comments_url(42), {"id": 100, "comment": "first"})

    result = await hc.add_comments(ctx, AddCommentsParams(task_id=42, comments=["first", "second", "third"]))

    assert result.status == "success"
    assert result.data["succeeded_count"] == 3
    assert result.data["failed_count"] == 0
    assert len(result.data["results"]) == 3


async def test_add_comments_resolves_task_by_name_and_bucket():
    """Two tasks share the title 'Ship it'; only #1 sits in the named bucket,
    so bucket_name must disambiguate down to exactly that one before posting."""
    ctx = MockContext()
    ctx.http.mock_get(f"{BRIDGE}/v1/tasks/all", [
        {"id": 1, "title": "Ship it", "project_id": 3},
        {"id": 2, "title": "Ship it", "project_id": 3},
    ])
    # Registration order matters: MockHTTP._find matches by substring in the
    # order mocks were registered, and "/v1/projects/3/views" is itself a
    # substring of "/v1/projects/3/views/7/tasks" — the more specific path
    # must be registered first or it never gets reached.
    # _filter_tasks_by_bucket parses this as a list of BUCKETS, each carrying
    # its own nested `tasks` array and a `title` to match bucket_name against
    # — not a flat list of tasks with a bucket_id field.
    ctx.http.mock_get(f"{BRIDGE}/v1/projects/3/views/7/tasks", [
        {"id": 9, "title": "Doing", "tasks": [{"id": 1}]},
        {"id": 10, "title": "Backlog", "tasks": [{"id": 2}]},
    ])
    ctx.http.mock_get(f"{BRIDGE}/v1/projects/3/views", [{"id": 7, "view_kind": "kanban"}])
    ctx.http.mock_post(_comments_url(1), {"id": 200, "comment": "note"})

    result = await hc.add_comments(
        ctx, AddCommentsParams(task_name="Ship it", bucket_name="Doing", comments=["note"]),
    )

    assert result.status == "success", result.data
    assert result.data["succeeded_count"] == 1
    assert result.data["results"][0]["task_id"] == 1


async def test_add_comments_rejects_empty_batch():
    ctx = MockContext()
    try:
        params = AddCommentsParams(task_id=42, comments=[])
    except Exception:
        return  # pydantic min_length=1 already rejects it at the schema level — acceptable either way
    result = await hc.add_comments(ctx, params)
    assert result.status == "error"
