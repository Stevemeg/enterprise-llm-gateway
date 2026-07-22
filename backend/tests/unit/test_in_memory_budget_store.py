"""InMemoryBudgetStore tests (ADR-0016 Slice 8): idempotent recording.

The identifier reused here (``idempotency_key``) is the request's ``correlation_id`` - the only
stable identifier the current architecture attaches to one execution attempt. Nothing here claims
this survives a process restart or coordinates across replicas (documented in the port and the
adapter's module docstring); it only proves that *retrying the same accounting call in this
process* cannot charge the same execution twice.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.budget.in_memory_budget_store import InMemoryBudgetStore
from gateway.application.ports.budget import BudgetUnavailableError
from gateway.application.ports.money import Money

ORG = uuid4()


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


async def test_recording_the_same_key_twice_charges_only_once() -> None:
    """A retried accounting call must not double-charge the execution it retried."""
    store = InMemoryBudgetStore({ORG: _money("100")})

    await store.record(ORG, _money("10"), idempotency_key="corr-1")
    await store.record(ORG, _money("10"), idempotency_key="corr-1")

    snapshot = await store.snapshot(ORG)
    assert snapshot is not None
    assert snapshot.spent == _money("10")


async def test_recording_different_keys_charges_each() -> None:
    """Two genuinely different executions must each be accounted for."""
    store = InMemoryBudgetStore({ORG: _money("100")})

    await store.record(ORG, _money("10"), idempotency_key="corr-1")
    await store.record(ORG, _money("10"), idempotency_key="corr-2")

    snapshot = await store.snapshot(ORG)
    assert snapshot is not None
    assert snapshot.spent == _money("20")


async def test_unavailable_store_raises_on_both_operations() -> None:
    store = InMemoryBudgetStore({ORG: _money("100")}, unavailable=True)

    with pytest.raises(BudgetUnavailableError):
        await store.snapshot(ORG)
    with pytest.raises(BudgetUnavailableError):
        await store.record(ORG, _money("1"), idempotency_key="corr-1")


async def test_unconfigured_org_reports_no_snapshot() -> None:
    store = InMemoryBudgetStore()
    assert await store.snapshot(uuid4()) is None
