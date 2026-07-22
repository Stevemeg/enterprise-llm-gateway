"""BudgetEnforcer tests (ADR-0016 Slice 8).

Fail-safe paths first: an unreachable budget store must fail closed (ADR-0009 row 1), and a
currency mismatch is a configuration defect, never a budget denial.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.budget.in_memory_budget_store import InMemoryBudgetStore
from gateway.application.accounting.budget_enforcer import (
    BudgetDecision,
    BudgetEnforcer,
    BudgetOutcome,
)
from gateway.application.ports.budget import UnsupportedCurrencyError
from gateway.application.ports.money import Money

ORG_A = uuid4()
ORG_B = uuid4()


def _money(amount: str, currency: str = "USD") -> Money:
    return Money(Decimal(amount), currency)


# ------------------------------------------------------------------ fail-safe paths first


async def test_unavailable_store_fails_closed() -> None:
    """ADR-0009 row 1: a hard budget store outage must reject, never silently allow."""
    enforcer = BudgetEnforcer(InMemoryBudgetStore(unavailable=True))

    decision = await enforcer.evaluate(ORG_A, _money("10"))

    assert decision.outcome is BudgetOutcome.UNAVAILABLE
    assert decision.permitted is False


async def test_currency_mismatch_is_a_defect_not_a_denial() -> None:
    store = InMemoryBudgetStore({ORG_A: _money("100", "USD")})
    enforcer = BudgetEnforcer(store)

    with pytest.raises(UnsupportedCurrencyError):
        await enforcer.evaluate(ORG_A, _money("10", "EUR"))


def test_snapshot_rejects_a_spent_amount_in_a_different_currency_than_its_limit() -> None:
    """A defensive check inside the DTO itself, not only at the enforcer boundary."""
    from gateway.application.ports.budget import BudgetSnapshot

    with pytest.raises(UnsupportedCurrencyError):
        BudgetSnapshot(organization_id=ORG_A, limit=_money("100", "USD"), spent=_money("10", "EUR"))


# ------------------------------------------------------------------ business outcomes


async def test_no_budget_configured_is_allowed_unbounded() -> None:
    """Distinct from an unreachable store: an org simply has no policy in effect."""
    enforcer = BudgetEnforcer(InMemoryBudgetStore())  # empty - no orgs configured

    decision = await enforcer.evaluate(ORG_A, _money("1000000"))

    assert decision.outcome is BudgetOutcome.ALLOWED
    assert decision.permitted is True
    assert decision.remaining is None


async def test_cost_within_remaining_budget_is_allowed() -> None:
    store = InMemoryBudgetStore({ORG_A: _money("100")})
    enforcer = BudgetEnforcer(store)

    decision = await enforcer.evaluate(ORG_A, _money("50"))

    assert decision.outcome is BudgetOutcome.ALLOWED
    assert decision.remaining == _money("100")


async def test_cost_exceeding_remaining_budget_is_denied() -> None:
    store = InMemoryBudgetStore({ORG_A: _money("100")})
    await store.record(ORG_A, _money("90"), idempotency_key="corr-1")
    enforcer = BudgetEnforcer(store)

    decision = await enforcer.evaluate(ORG_A, _money("20"))

    assert decision.outcome is BudgetOutcome.EXCEEDED
    assert decision.permitted is False
    assert decision.remaining == _money("10")


async def test_exact_boundary_cost_equal_to_remaining_is_allowed() -> None:
    """Spending exactly the last unit of budget must not be treated as exceeding it."""
    store = InMemoryBudgetStore({ORG_A: _money("100")})
    await store.record(ORG_A, _money("90"), idempotency_key="corr-1")
    enforcer = BudgetEnforcer(store)

    decision = await enforcer.evaluate(ORG_A, _money("10"))

    assert decision.outcome is BudgetOutcome.ALLOWED


async def test_one_cent_over_the_boundary_is_denied() -> None:
    store = InMemoryBudgetStore({ORG_A: _money("100")})
    await store.record(ORG_A, _money("90"), idempotency_key="corr-1")
    enforcer = BudgetEnforcer(store)

    decision = await enforcer.evaluate(ORG_A, _money("10.00000001"))

    assert decision.outcome is BudgetOutcome.EXCEEDED


# ------------------------------------------------------------------ tenant isolation


async def test_recording_for_one_org_does_not_affect_another() -> None:
    store = InMemoryBudgetStore({ORG_A: _money("100"), ORG_B: _money("100")})
    await store.record(ORG_A, _money("90"), idempotency_key="corr-1")
    enforcer = BudgetEnforcer(store)

    decision_a = await enforcer.evaluate(ORG_A, _money("0"))
    decision_b = await enforcer.evaluate(ORG_B, _money("0"))

    assert decision_a.remaining == _money("10")
    assert decision_b.remaining == _money("100")


# ------------------------------------------------------------------ decision identity


def test_budget_decision_is_the_only_explanation_object() -> None:
    import dataclasses

    fields = {f.name for f in dataclasses.fields(BudgetDecision)}
    assert fields == {"outcome", "organization_id", "cost", "remaining", "limit"}
