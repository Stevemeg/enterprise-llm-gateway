"""Composite authentication audit sink (ADR-0009, FR-101).

Fans one ``AuthAuditEvent`` out to several sinks so the durable, hash-chained ``audit_event``
sink can be added alongside structured logging without touching a single call site.

**A sink failure must never break authentication or swallow the record.** Each sink is invoked
independently; if one raises, the error is logged and the remaining sinks still run. Losing an
audit line is bad, but failing an otherwise-valid login because a log shipper hiccuped is worse
— and silently dropping the event without a trace would be worst of all.
"""

from __future__ import annotations

from collections.abc import Sequence

from gateway.application.ports.auth import AuthAuditSink
from gateway.domain.auth.models import AuthAuditEvent
from gateway.observability.logging import get_logger

_logger = get_logger("audit")


class CompositeAuthAuditSink:
    def __init__(self, sinks: Sequence[AuthAuditSink]) -> None:
        self._sinks = tuple(sinks)

    async def record(self, event: AuthAuditEvent) -> None:
        for sink in self._sinks:
            try:
                await sink.record(event)
            except Exception:
                _logger.exception(
                    "auth_audit_sink_failed",
                    sink=type(sink).__name__,
                    action=event.action,
                    result=event.result,
                )
