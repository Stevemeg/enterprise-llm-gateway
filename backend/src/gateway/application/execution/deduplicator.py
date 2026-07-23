"""Process-local in-flight request coalescing (ADR-0016 Slice 10).

## Cache identity vs. deduplication identity (Rule 3) - these are NOT the same concept

Cache identity (``cache_key.py``) is content-based and durable: two different requests (different
``correlation_id``) that ask for the same thing are the same cache entry, on purpose, forever.

Deduplication identity is ``(organization_id, correlation_id)`` - the opposite shape. It answers a
narrower question: is *this exact logical request* (the caller's own retry, a redundant concurrent
send of the same correlation id) already in flight right now? Two literal duplicates sharing a
correlation id must not each pay for and receive a separate provider call; two *different*
correlation ids that happen to carry identical content are not this class's concern - a cache hit
already serves both without a provider call once one of them has populated the cache, and if both
miss concurrently before either has, they proceed independently. That "cache stampede" case is a
known, explicitly out-of-scope limitation (see the evidence log), distinct from what this class
guarantees.

## This is process-local only, not distributed

Coalescing is a plain ``dict`` of ``asyncio.Task``, alive only as long as this process is. It gives
no protection across two gateway replicas that each receive the same correlation id at the same
moment - closing that gap would need a distributed lock (Redis, or the same PostgreSQL
advisory-lock primitive ``SqlBudgetLedger.reserve`` already uses), which is not built here because
nothing in this milestone demonstrates a need for it beyond the single-process guarantee (GP-1 -
evidence, not a hypothetical future requirement). ``ReservationService``/``SqlBudgetLedger``'s own
idempotency (Slice 9) remains the durable, cross-process backstop against *double-charging* even
in a case this coalescer cannot prevent a double *provider call* for (two separate processes).

## Why a Task, not a Future, and why ``asyncio.shield``

Every caller - the one that starts the operation and every one that joins it - awaits the *same*
``asyncio.Task`` object. Awaiting it through ``asyncio.shield`` means a caller that is itself
cancelled (e.g. its own request timed out) does not cancel the underlying operation for every other
caller sharing it; the operation keeps running to completion (and is still removed from the
in-flight map when it finishes) even if every original awaiter has since given up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast
from uuid import UUID

T = TypeVar("T")


class RequestDeduplicator:
    """Ensures at most one concurrent execution per ``(organization_id, correlation_id)``."""

    def __init__(self) -> None:
        self._in_flight: dict[tuple[UUID, str], asyncio.Task[Any]] = {}

    async def coalesce(
        self,
        organization_id: UUID,
        correlation_id: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        """Run ``operation`` once per key; concurrent callers sharing the key await the same
        result (success or failure) instead of each starting their own attempt."""
        key = (organization_id, correlation_id)
        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.ensure_future(operation())
            self._in_flight[key] = task

            def _forget(done: asyncio.Task[Any], key: tuple[UUID, str] = key) -> None:
                if self._in_flight.get(key) is done:
                    del self._in_flight[key]

            task.add_done_callback(_forget)
        return cast(T, await asyncio.shield(task))
