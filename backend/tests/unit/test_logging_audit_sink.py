"""Tests for the structured-logging auth audit sink."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from gateway.adapters.audit.logging_sink import LoggingAuthAuditSink
from gateway.domain.auth.models import AuthAuditEvent
from gateway.observability.logging import configure_logging


async def test_audit_event_is_emitted_as_structured_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(level="info", json_output=True)
    await LoggingAuthAuditSink().record(
        AuthAuditEvent(
            action="request.authenticated",
            result="success",
            organization_id=uuid4(),
            principal_type="user",
            subject_id=uuid4(),
        )
    )
    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "auth_audit"
    assert data["action"] == "request.authenticated"
    assert data["result"] == "success"
    assert data["principal_type"] == "user"
