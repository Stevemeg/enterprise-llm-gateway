"""Clock and Sleeper tests (Slice 11 adds Sleeper).

``AsyncioSleeper`` is the production implementation of the ``Sleeper`` seam. Its own test is the
one place a real (sub-millisecond) sleep is appropriate: elapsing time *is* this adapter's entire
job, so a fake here would test nothing. Every consumer of ``Sleeper`` - notably the retry loop -
injects a recording double instead and never sleeps in real time.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from gateway.shared.clock import AsyncioSleeper, Clock, Sleeper, SystemClock


def test_system_clock_returns_timezone_aware_utc() -> None:
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5


def test_both_time_abstractions_satisfy_their_protocols() -> None:
    assert isinstance(SystemClock(), Clock)
    assert isinstance(AsyncioSleeper(), Sleeper)


async def test_asyncio_sleeper_actually_elapses_the_requested_duration() -> None:
    started = time.monotonic()

    await AsyncioSleeper().sleep(timedelta(milliseconds=5))

    assert time.monotonic() - started >= 0.004


async def test_a_zero_or_negative_duration_is_a_no_op() -> None:
    """A retry policy with no configured backoff must not pay for a scheduler round-trip."""
    started = time.monotonic()

    await AsyncioSleeper().sleep(timedelta(0))
    await AsyncioSleeper().sleep(timedelta(seconds=-1))

    assert time.monotonic() - started < 0.5
