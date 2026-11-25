"""Unit tests for tasks AI tools."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from imperal_sdk.chat import ActionResult

from handlers_ai import (
    AiEstimateDurationParams,
    AiPlanMyDayParams,
    AiProjectSummaryParams,
    ai_estimate_duration,
    ai_plan_my_day,
    ai_project_summary,
)


class MockUser:
    def __init__(self, imperal_id="usr_test123"):
        self.imperal_id = imperal_id


class MockContext:
    def __init__(self, imperal_id="usr_test123"):
        self.user = MockUser(imperal_id)
        self.ai = MagicMock()
        self.http = MagicMock()
        self.http.get = AsyncMock()
        self.http.post = AsyncMock()
        self.http.delete = AsyncMock()
        self.http.put = AsyncMock()
        self.secrets = MagicMock()
        self.secrets.get = AsyncMock(return_value="test_bridge_key")


@pytest.mark.asyncio
async def test_ai_estimate_duration_success(monkeypatch):
    ctx = MockContext()
    completion_mock = MagicMock()
    completion_mock.text = '{"estimated_minutes": 120, "confidence": "high", "rationale": "Moderate complexity", "suggested_breakdown": ["Research", "Implement"]}'
    ctx.ai.complete = AsyncMock(return_value=completion_mock)

    async def fake_api_get(c, path, params=None):
        if path == "/v1/tasks/10":
            return {"id": 10, "title": "Implement caching", "description": "Add redis caching layer", "priority": 3}
        if path == "/v1/tasks/10/subtasks":
            return []
        return {}

    monkeypatch.setattr("handlers_ai.api_get", fake_api_get)

    params = AiEstimateDurationParams(task_id=10)
    res = await ai_estimate_duration(ctx, params)

    assert isinstance(res, ActionResult)
    data = res.to_dict().get("data", {})
    assert data["task_id"] == 10
    assert data["estimated_minutes"] == 120
    assert data["confidence"] == "high"
    assert "Research" in data["suggested_breakdown"]


@pytest.mark.asyncio
async def test_ai_plan_my_day_success(monkeypatch):
    ctx = MockContext()
    completion_mock = MagicMock()
    completion_mock.text = '''{
        "summary": "Focus on high-priority security fix first.",
        "scheduled_tasks": [
            {"task_id": 101, "title": "Patch CVE", "priority": 5, "due_date": "2026-11-25T18:00:00Z", "time_slot": "09:00 - 11:00", "estimated_minutes": 120, "reason": "Urgent"}
        ],
        "total_estimated_minutes": 120,
        "recommendations": ["Avoid context switching", "Take 10m break"]
    }'''
    ctx.ai.complete = AsyncMock(return_value=completion_mock)

    async def fake_fetch_all_pages(c, params):
        return [
            {"id": 101, "title": "Patch CVE", "priority": 5, "due_date": "2026-11-25T18:00:00Z", "done": False},
            {"id": 102, "title": "Done task", "priority": 1, "done": True},
        ]

    monkeypatch.setattr("handlers_ai.fetch_all_pages", fake_fetch_all_pages)

    params = AiPlanMyDayParams(target_hours=8)
    res = await ai_plan_my_day(ctx, params)

    assert isinstance(res, ActionResult)
    data = res.to_dict().get("data", {})
    assert len(data["scheduled_tasks"]) == 1
    assert data["scheduled_tasks"][0]["task_id"] == 101
    assert data["total_estimated_minutes"] == 120
    assert len(data["recommendations"]) == 2


@pytest.mark.asyncio
async def test_ai_project_summary_success(monkeypatch):
    ctx = MockContext()
    completion_mock = MagicMock()
    completion_mock.text = '''{
        "health": "on_track",
        "key_findings": ["All tasks proceeding normally"],
        "next_priorities": ["Complete staging deploy"],
        "summary_markdown": "### Executive Briefing\\nProject is on track."
    }'''
    ctx.ai.complete = AsyncMock(return_value=completion_mock)

    async def fake_api_get(c, path, params=None):
        if path == "/v1/projects":
            return [{"id": 5, "title": "Imperal Migration"}]
        if path == "/v1/projects/5":
            return {"id": 5, "title": "Imperal Migration"}
        return {}

    async def fake_fetch_all_pages(c, params):
        return [
            {"id": 1, "title": "Task 1", "done": True, "due_date": None},
            {"id": 2, "title": "Task 2", "done": False, "due_date": "2026-12-01T10:00:00Z"},
        ]

    monkeypatch.setattr("handlers_ai.api_get", fake_api_get)
    monkeypatch.setattr("handlers_ai.fetch_all_pages", fake_fetch_all_pages)

    params = AiProjectSummaryParams(project_id=5)
    res = await ai_project_summary(ctx, params)

    assert isinstance(res, ActionResult)
    data = res.to_dict().get("data", {})
    assert data["project_id"] == 5
    assert data["health"] == "on_track"
    assert data["total_tasks"] == 2
    assert data["completed_tasks"] == 1
    assert "Executive Briefing" in data["summary_markdown"]
