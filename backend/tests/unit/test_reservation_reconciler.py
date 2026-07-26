"""ReservationReconciler tests (Phase 5 M2).

The dangerous direction first. Reconciliation exists to *return* money, so the failure that
matters is not "a stale hold survived" - it is "a **live** hold was reclaimed", which would let a
tenant reserve the same money twice and overspend. Every test here is written against that.

Atomicity, two racing reconcilers, and the reconciler-vs-settlement race are proven only against
real PostgreSQL (``tests/integration/test_reservation_reconciliation_postgres.py``); the in-memory
ledger cannot demonstrate them and this file does not pretend it can.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.application.accounting.reservation_reconciler import (
    DEFAULT_RESERVATION_TTL,
    ReservationReconciler,
)
from gateway.application.ports.ledger import ReservationOutcome
from gateway.application.ports.money import Money

ORG = uuid4()
OTHER_ORG = uuid4()
LIMIT = Decimal("100")
HOLD = Money(Decimal("10"), "USD")
TTL = timedelta(minutes=15)


class MovableClock:
    """A clock a test can advance, so a hold can age without anybody sleeping."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self.moment

    def advance(self, delta: timedelta) -> None:
        self.moment += delta


def _ledger(clock: MovableClock) -> InMemoryBudgetLedger:
    return InMemoryBudgetLedger(
        {ORG: Money(LIMIT, "USD"), OTHER_ORG: Money(LIMIT, "USD")}, clock=clock
    )


async def _remaining(ledger: InMemoryBudgetLedger, org: object = ORG) -> Decimal:
    """Read headroom through the port: an over-large probe is refused and reports what is left,
    and a refused reservation holds nothing."""
    probe = await ledger.reserve(org, f"probe-{uuid4()}", Money(Decimal("1000000"), "USD"))  # type: ignore[arg-type]
    assert probe.outcome is ReservationOutcome.EXCEEDED
    assert probe.remaining is not None
    return probe.remaining.amount


# ---------------------------------------------------------------- do no harm


async def test_a_live_hold_is_never_reclaimed() -> None:
    """The failure that would be worse than the leak. A hold younger than the TTL belongs to a
    request that may still be running, and returning it would let the tenant spend it twice."""
    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "live", HOLD)
    reconciler = ReservationReconciler(ledger, clock, TTL)

    clock.advance(TTL - timedelta(seconds=1))
    assert await reconciler.reclaim(ORG) == 0
    assert await _remaining(ledger) == LIMIT - HOLD.amount


async def test_a_settled_hold_is_never_reclaimed() -> None:
    """Its money already moved to ``spent``; touching it again would credit the tenant twice."""
    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "done", HOLD)
    await ledger.release(ORG, "done")
    reconciler = ReservationReconciler(ledger, clock, TTL)

    clock.advance(TTL * 10)

    assert await reconciler.reclaim(ORG) == 0
    assert await _remaining(ledger) == LIMIT


async def test_one_tenants_sweep_never_touches_another() -> None:
    """Tenant scoping is what lets this run as ``app_rw`` under FORCE RLS instead of needing a
    privileged cross-tenant sweep - so it must be asserted, not assumed from the signature."""
    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "mine", HOLD)
    await ledger.reserve(OTHER_ORG, "theirs", HOLD)
    reconciler = ReservationReconciler(ledger, clock, TTL)

    clock.advance(TTL * 2)
    reclaimed = await reconciler.reclaim(ORG)

    assert reclaimed == 1
    assert await _remaining(ledger, ORG) == LIMIT
    assert await _remaining(ledger, OTHER_ORG) == LIMIT - HOLD.amount


# ---------------------------------------------------------------- reclaim what is genuinely dead


async def test_a_hold_older_than_the_ttl_is_reclaimed_exactly_once() -> None:
    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "abandoned", HOLD)
    reconciler = ReservationReconciler(ledger, clock, TTL)

    clock.advance(TTL + timedelta(seconds=1))

    assert await reconciler.reclaim(ORG) == 1
    assert await _remaining(ledger) == LIMIT


async def test_repeated_reconciliation_is_idempotent() -> None:
    """A second sweep must find nothing - not reclaim the same hold again and hand back money
    that was already handed back."""
    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "abandoned", HOLD)
    reconciler = ReservationReconciler(ledger, clock, TTL)
    clock.advance(TTL * 2)

    first = await reconciler.reclaim(ORG)
    second = await reconciler.reclaim(ORG)
    third = await reconciler.reclaim(ORG)

    assert (first, second, third) == (1, 0, 0)
    assert await _remaining(ledger) == LIMIT


async def test_a_reclaimed_hold_frees_budget_the_tenant_can_immediately_use() -> None:
    """The point of doing this on the reserve path: the tenant that was blocked by its own dead
    holds is unblocked by the very next request rather than staying locked out."""
    clock = MovableClock()
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("10"), "USD")}, clock=clock)
    await ledger.reserve(ORG, "abandoned", Money(Decimal("10"), "USD"))
    blocked = await ledger.reserve(ORG, "next", Money(Decimal("10"), "USD"))
    assert blocked.outcome is ReservationOutcome.EXCEEDED

    clock.advance(TTL * 2)
    await ReservationReconciler(ledger, clock, TTL).reclaim(ORG)

    unblocked = await ledger.reserve(ORG, "next", Money(Decimal("10"), "USD"))
    assert unblocked.outcome is ReservationOutcome.RESERVED


async def test_a_late_settlement_after_expiry_books_spend_without_double_crediting() -> None:
    """The interaction the port documents. The tokens were really consumed, so the spend must be
    booked; the hold is already back, so it must not be returned a second time - which would
    drive ``reserved`` below what is held and, at the boundary, below zero."""
    from gateway.application.ports.ledger import SettlementDetail

    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "slow", HOLD)
    clock.advance(TTL * 2)
    await ReservationReconciler(ledger, clock, TTL).reclaim(ORG)
    assert await _remaining(ledger) == LIMIT

    await ledger.settle(
        ORG,
        "slow",
        SettlementDetail(
            provider="openai",
            model="gpt-4o",
            prompt_tokens=1,
            completion_tokens=1,
            input_cost=Money(Decimal("1"), "USD"),
            output_cost=Money(Decimal("1"), "USD"),
            total_cost=Money(Decimal("2"), "USD"),
        ),
    )

    # Exactly the actual spend was charged, and the reclaimed hold was not credited twice.
    assert await _remaining(ledger) == LIMIT - Decimal("2")


async def test_reserving_the_same_id_after_expiry_takes_a_real_hold_again() -> None:
    """An ``expired`` row must not replay as RESERVED: it would report a hold while holding
    nothing - the phantom-hold defect the Slice-11 analysis found for ``released`` rows, which
    ``expired`` reintroduced the moment reconciliation could write it."""
    clock = MovableClock()
    ledger = _ledger(clock)
    await ledger.reserve(ORG, "recycled", HOLD)
    clock.advance(TTL * 2)
    await ReservationReconciler(ledger, clock, TTL).reclaim(ORG)

    again = await ledger.reserve(ORG, "recycled", HOLD)

    assert again.outcome is ReservationOutcome.RESERVED
    assert await _remaining(ledger) == LIMIT - HOLD.amount


# ------------------------------------------------ the reconciler cannot break a request


async def test_a_ledger_outage_is_swallowed_rather_than_failing_the_caller() -> None:
    """A repair that could not run is not a reason to refuse an inference. Skipping a reclaim can
    only ever leave the tenant with *less* headroom, never more, so this is not a relaxation of
    ADR-0009 row 1 - that rule exists to prevent unbounded spend."""
    clock = MovableClock()
    ledger = InMemoryBudgetLedger({ORG: Money(LIMIT, "USD")}, unavailable=True, clock=clock)

    reclaimed = await ReservationReconciler(ledger, clock, TTL).reclaim(ORG)
    assert reclaimed == 0


def test_a_non_positive_ttl_is_rejected_at_construction() -> None:
    """A zero or negative TTL would make every hold instantly stale, reclaiming live reservations
    on every request - the overspend failure. It must be impossible to configure, not merely
    discouraged."""
    clock = MovableClock()
    ledger = _ledger(clock)
    for bad in (timedelta(0), timedelta(seconds=-1)):
        with pytest.raises(ValueError, match="must be positive"):
            ReservationReconciler(ledger, clock, bad)


def test_the_default_ttl_is_far_longer_than_any_request_this_gateway_can_make() -> None:
    """Pins the safety margin rather than leaving it to a comment: the longest possible request is
    three reflection attempts at the 30s default provider timeout."""
    longest_possible_request = timedelta(seconds=30) * 3
    assert longest_possible_request * 5 < DEFAULT_RESERVATION_TTL
