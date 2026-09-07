"""Tests for bulk complete and uncomplete tasks with time-travel undo."""
import pytest
from imperal_sdk.testing import MockContext
import handlers_crud
from handlers_crud import CompleteTasksParams


BRIDGE = "https://bridge.test"


@pytest.mark.asyncio
async def test_complete_tasks_with_undo():
    ctx = MockContext(user_id="user-1")

    # Mock resolving and completing two tasks by ID
    ctx.http.mock_post(f"{BRIDGE}/v1/tasks/101", {"id": 101, "title": "Task One", "done": True})
    ctx.http.mock_post(f"{BRIDGE}/v1/tasks/102", {"id": 102, "title": "Task Two", "done": True})

    params = CompleteTasksParams(task_ids=[101, 102])
    res = await handlers_crud.complete_tasks(ctx, params)

    assert res.status == "success"
    assert res.data["succeeded_count"] == 2
    assert res.data["failed_count"] == 0
    assert res.undo is not None
    assert res.undo["function"] == "uncomplete_tasks"
    assert res.undo["params"]["task_ids"] == [101, 102]


@pytest.mark.asyncio
async def test_uncomplete_tasks_bulk():
    ctx = MockContext(user_id="user-1")

    ctx.http.mock_post(f"{BRIDGE}/v1/tasks/101", {"id": 101, "title": "Task One", "done": False})
    ctx.http.mock_post(f"{BRIDGE}/v1/tasks/102", {"id": 102, "title": "Task Two", "done": False})

    params = CompleteTasksParams(task_ids=[101, 102])
    res = await handlers_crud.uncomplete_tasks(ctx, params)

    assert res.status == "success"
    assert res.data["succeeded_count"] == 2
    assert res.data["failed_count"] == 0
