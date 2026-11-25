"""Tests for SDK 6.9.0 needs_human contract and connection error handling."""

import pytest
from app import bridge_error_result, is_no_connection_error


def test_bridge_error_result_no_connection():
    resp = {"status": "error", "code": "no_connection", "detail": "User not connected"}
    assert is_no_connection_error(resp) is True

    result = bridge_error_result(resp, "Action failed")
    assert result.status == "error"
    assert result.error_code == "AUTH_EXPIRED"
    assert "No Vikunja connected" in result.error

    # Verify needs_human structure from SDK 6.9.0
    res_dict = result.to_dict()
    assert res_dict.get("needs_human") is not None
    assert res_dict["needs_human"]["kind"] == "means"
    assert "Vikunja" in res_dict["needs_human"]["what"]


def test_bridge_error_result_generic():
    resp = {"status": "error", "detail": "Task 123 not found"}
    assert is_no_connection_error(resp) is False

    result = bridge_error_result(resp, "Couldn't fetch task", default_code="TASKS_TASK_NOT_FOUND")
    assert result.status == "error"
    assert result.error_code == "TASKS_TASK_NOT_FOUND"
    assert "Task 123 not found" in result.error
