"""Structured-logging authentication audit sink (implements AuthAuditSink).

Emits one structured, correlation-id-bearing log line per authentication decision
(FR-101). A durable, hash-chained ``audit_event`` sink (ADR-0009) is added with the
eventing milestone; this sink is the interim, always-on record.
"""

from __future__ import annotations

from gateway.domain.auth.models import AuthAuditEvent
from gateway.observability.logging import get_logger

_logger = get_logger("audit")


class LoggingAuthAuditSink:
    async def record(self, event: AuthAuditEvent) -> None:
        _logger.info(
            "auth_audit",
            action=event.action,
            result=event.result,
            organization_id=str(event.organization_id) if event.organization_id else None,
            principal_type=event.principal_type,
            subject_id=str(event.subject_id) if event.subject_id else None,
            detail=event.detail,
        )
