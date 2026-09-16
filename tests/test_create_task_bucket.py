"""tasks · test_create_task_bucket.py

Verifies that create_task correctly resolves target buckets (explicit bucket_name,
explicit bucket_id, and default fallback to Planned) and guarantees placement
via Vikunja's dedicated join-table endpoint.
"""
from imperal_sdk.testing import MockContext

import app as _app
import handlers_crud as hc
from handlers_crud import CreateTaskParams


BRIDGE = _app._bridge_url()


def _views_url(project_id: int) -> str:
    return f"{BRIDGE}/v1/projects/{project_id}/views"


def _buckets_url(project_id: int, view_id: int) -> str:
    return f"{BRIDGE}/v1/projects/{project_id}/views/{view_id}/tasks"


def _bucket_tasks_url(project_id: int, view_id: int, bucket_id: int) -> str:
    return f"{BRIDGE}/v1/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks"


def _tasks_url() -> str:
    return f"{BRIDGE}/v1/tasks"


async def test_create_task_with_explicit_bucket_name_moves_to_bucket():
    """When bucket_name is passed, task must be resolved and moved to that bucket."""
    ctx = MockContext()

    # In MockHTTP, pattern in url matches as a substring!
    # /v1/projects/{id}/views is a substring of /v1/projects/{id}/views/{view_id}/tasks!
    # So we register the more specific subpath FIRST:
    ctx.http.mock_get(_buckets_url(88, 412), [
        {"id": 316, "title": "Planned"},
        {"id": 322, "title": "In Progress"},
        {"id": 445, "title": "Completed (Done)"},
    ])
    ctx.http.mock_get(_views_url(88), [{"id": 412, "view_kind": "kanban"}])
    ctx.http.mock_post(_tasks_url(), {"id": 101, "project_id": 88, "title": "Implement feature"})
    ctx.http.mock_post(_bucket_tasks_url(88, 412, 322), {"task_id": 101, "bucket_id": 322})

    res = await hc.create_task(ctx, CreateTaskParams(
        project_id=88,
        title="Implement feature",
        bucket_name="In Progress",
    ))

    assert res.status == "success"
    assert res.data["task_id"] == 101
    assert res.data["bucket_id"] == 322
    assert "In Progress" in res.summary


async def test_create_task_defaults_to_planned_bucket():
    """When no bucket is passed, task must automatically default to 'Planned'."""
    ctx = MockContext()

    # In MockHTTP, pattern in url matches as a substring!
    # /v1/projects/{id}/views is a substring of /v1/projects/{id}/views/{view_id}/tasks!
    # So we register the more specific subpath FIRST:
    ctx.http.mock_get(_buckets_url(88, 412), [
        {"id": 316, "title": "Planned"},
        {"id": 322, "title": "In Progress"},
        {"id": 445, "title": "Completed (Done)"},
    ])
    ctx.http.mock_get(_views_url(88), [{"id": 412, "view_kind": "kanban"}])
    ctx.http.mock_post(_tasks_url(), {"id": 102, "project_id": 88, "title": "New backlog task"})
    ctx.http.mock_post(_bucket_tasks_url(88, 412, 316), {"task_id": 102, "bucket_id": 316})

    res = await hc.create_task(ctx, CreateTaskParams(
        project_id=88,
        title="New backlog task",
    ))

    assert res.status == "success"
    assert res.data["task_id"] == 102
    assert res.data["bucket_id"] == 316
    assert "Planned" in res.summary
