"""RequestDeduplicator tests (ADR-0016 Slice 10).

Uses real ``asyncio`` concurrency (``asyncio.gather`` over coroutines that yield control via
``asyncio.sleep``/an ``asyncio.Event``), not sequential calls dressed up as concurrent - a
single-threaded event loop can hide a broken coalescing guarantee if callers never actually
overlap. These tests are unit tests (no I/O), not integration tests: the concurrency here is
genuine asyncio task interleaving, which - unlike PostgreSQL locking - a single process can prove
without a database.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from gateway.application.execution.deduplicator import RequestDeduplicator

ORG = uuid4()
OTHER_ORG = uuid4()


class _CountingOperation:
    """An awaitable operation that counts how many times it actually ran and can be released
    on demand, so a test can guarantee true overlap instead of hoping for it."""

    def __init__(self) -> None:
        self.call_count = 0
        self._release = asyncio.Event()

    def release(self) -> None:
        self._release.set()

    async def __call__(self) -> str:
        self.call_count += 1
        await self._release.wait()
        return f"result-{self.call_count}"


async def test_a_single_call_runs_the_operation_once() -> None:
    dedup = RequestDeduplicator()
    op = _CountingOperation()
    op.release()

    result = await dedup.coalesce(ORG, "c1", op)

    assert result == "result-1"
    assert op.call_count == 1


async def test_concurrent_duplicate_calls_share_one_execution() -> None:
    dedup = RequestDeduplicator()
    op = _CountingOperation()

    task_a = asyncio.ensure_future(dedup.coalesce(ORG, "c1", op))
    task_b = asyncio.ensure_future(dedup.coalesce(ORG, "c1", op))
    await asyncio.sleep(0)  # let both tasks reach op.__call__ and register as in-flight
    op.release()
    result_a, result_b = await asyncio.gather(task_a, task_b)

    assert op.call_count == 1, "the provider-equivalent operation must run exactly once"
    assert result_a == result_b == "result-1"


async def test_different_correlation_ids_do_not_coalesce() -> None:
    dedup = RequestDeduplicator()
    op = _CountingOperation()

    task_a = asyncio.ensure_future(dedup.coalesce(ORG, "c1", op))
    task_b = asyncio.ensure_future(dedup.coalesce(ORG, "c2", op))
    await asyncio.sleep(0)
    op.release()
    await asyncio.gather(task_a, task_b)

    assert op.call_count == 2


async def test_different_organizations_with_the_same_correlation_id_do_not_coalesce() -> None:
    """Deduplication must not collapse two logically separate tenants' requests across the
    tenant boundary, even if they happen to reuse the same caller-supplied correlation id."""
    dedup = RequestDeduplicator()
    op = _CountingOperation()

    task_a = asyncio.ensure_future(dedup.coalesce(ORG, "shared-id", op))
    task_b = asyncio.ensure_future(dedup.coalesce(OTHER_ORG, "shared-id", op))
    await asyncio.sleep(0)
    op.release()
    await asyncio.gather(task_a, task_b)

    assert op.call_count == 2


async def test_a_new_call_after_completion_runs_again_rather_than_replaying() -> None:
    dedup = RequestDeduplicator()
    op = _CountingOperation()
    op.release()
    await dedup.coalesce(ORG, "c1", op)

    op._release = asyncio.Event()
    op.release()
    await dedup.coalesce(ORG, "c1", op)

    assert op.call_count == 2


async def test_a_failure_propagates_to_every_coalesced_waiter() -> None:
    dedup = RequestDeduplicator()

    async def _boom() -> str:
        await asyncio.sleep(0)
        raise RuntimeError("provider exploded")

    task_a = asyncio.ensure_future(dedup.coalesce(ORG, "c1", _boom))
    task_b = asyncio.ensure_future(dedup.coalesce(ORG, "c1", _boom))

    with pytest.raises(RuntimeError, match="provider exploded"):
        await task_a
    with pytest.raises(RuntimeError, match="provider exploded"):
        await task_b


async def test_a_cancelled_waiter_does_not_cancel_the_operation_for_other_waiters() -> None:
    dedup = RequestDeduplicator()
    op = _CountingOperation()

    task_a = asyncio.ensure_future(dedup.coalesce(ORG, "c1", op))
    task_b = asyncio.ensure_future(dedup.coalesce(ORG, "c1", op))
    await asyncio.sleep(0)  # both register as in-flight before either is disturbed

    task_a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task_a

    op.release()
    result_b = await task_b

    assert result_b == "result-1"
    assert op.call_count == 1
