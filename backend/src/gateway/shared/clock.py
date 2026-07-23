"""Time abstractions.

A ``Clock`` port lets time-dependent code (health timestamps, TTLs, budget periods)
be tested deterministically by injecting a fake clock, keeping the domain free of
direct ``datetime.now`` calls. ``Sleeper`` is the same idea for *elapsing* time rather
than reading it (retry backoff, Slice 11): without it, a test of a bounded retry loop
would have to sleep in real wall-clock time to exercise the delay it is asserting on.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Returns the current time. Implementations must return timezone-aware UTC."""

    def now(self) -> datetime: ...


class SystemClock:
    """Production clock backed by the system wall clock (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@runtime_checkable
class Sleeper(Protocol):
    """Pauses execution for a duration. Separate from ``Clock`` because reading the time and
    elapsing it are different capabilities - a consumer that only needs one must not be handed
    the other (and most consumers of ``Clock`` must never be able to block)."""

    async def sleep(self, duration: timedelta) -> None: ...


class AsyncioSleeper:
    """Production sleeper backed by ``asyncio.sleep``. A non-positive duration is a no-op."""

    async def sleep(self, duration: timedelta) -> None:
        seconds = duration.total_seconds()
        if seconds > 0:
            await asyncio.sleep(seconds)
