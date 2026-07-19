"""Structured logging (Backend_Implementation_Guide.md §12).

* JSON logs in production, human-readable console in dev.
* Every log line is correlated by ``request_id`` via contextvars — no manual threading.
* A redaction processor guarantees secrets/credentials are never emitted (FR-010/082),
  a defense-in-depth backstop independent of call-site discipline.
"""

from __future__ import annotations

import logging

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

# Keys whose values must never be logged, regardless of source.
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "password",
        "key_hash",
        "cookie",
        "set-cookie",
    }
)
_REDACTED = "[redacted]"


def _redact_sensitive(
    _logger: WrappedLogger, _method_name: str, event_dict: EventDict
) -> EventDict:
    """Replace values of sensitive keys with a placeholder (case-insensitive)."""
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(*, level: str, json_output: bool) -> None:
    """Configure structlog process-wide. Idempotent; safe to call at startup."""
    min_level = _LEVELS.get(level.lower(), logging.INFO)
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    processors: list[Processor] = [
        merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        renderer,
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a bound logger; ``request_id`` (if set) is merged automatically."""
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger


def bind_request_context(*, request_id: str, **fields: str) -> None:
    """Bind correlation fields for the current context (request/task-scoped)."""
    bind_contextvars(request_id=request_id, **fields)


def clear_request_context() -> None:
    """Clear all bound context fields (call at the end of a request)."""
    clear_contextvars()
