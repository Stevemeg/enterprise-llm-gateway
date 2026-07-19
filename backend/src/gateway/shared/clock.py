"""Time abstraction.

A ``Clock`` port lets time-dependent code (health timestamps, TTLs, budget periods)
be tested deterministically by injecting a fake clock, keeping the domain free of
direct ``datetime.now`` calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Returns the current time. Implementations must return timezone-aware UTC."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production clock backed by the system wall clock (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)
