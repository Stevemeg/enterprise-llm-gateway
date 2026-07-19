"""Tests for structured logging: correlation binding and secret redaction."""

from __future__ import annotations

import json

import pytest

from gateway.observability.logging import (
    bind_request_context,
    clear_request_context,
    configure_logging,
    get_logger,
)


def _last_json_line(captured: str) -> dict[str, object]:
    line = captured.strip().splitlines()[-1]
    parsed: dict[str, object] = json.loads(line)
    return parsed


def test_context_is_merged_and_secrets_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="info", json_output=True)
    bind_request_context(request_id="req_test123", method="GET", path="/x")
    try:
        get_logger("test").info(
            "event_happened",
            authorization="Bearer super-secret",
            api_key="elg_live_secret",
            user="bob",
        )
    finally:
        clear_request_context()

    data = _last_json_line(capsys.readouterr().out)
    assert data["event"] == "event_happened"
    assert data["request_id"] == "req_test123"
    assert data["method"] == "GET"
    assert data["authorization"] == "[redacted]"
    assert data["api_key"] == "[redacted]"
    assert data["user"] == "bob"
    assert data["level"] == "info"


def test_debug_is_filtered_when_level_is_info(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="info", json_output=True)
    get_logger("test").debug("should_not_appear")
    assert capsys.readouterr().out.strip() == ""


def test_context_cleared_between_requests(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="info", json_output=True)
    bind_request_context(request_id="req_first")
    clear_request_context()
    get_logger("test").info("after_clear")
    data = _last_json_line(capsys.readouterr().out)
    assert "request_id" not in data
