"""InMemoryBudgetLedger tests (ADR-0016 Slice 9).

Fast, single-process tests of BudgetLedgerPort's business semantics. Does NOT prove atomicity
under real concurrency or RLS isolation - those are real-Postgres-only claims, proven separately
against SqlBudgetLedger (tests/integration/test_budget_ledger_postgres.py).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.application.ports.ledger import (
    LedgerUnavailableError,
    ReservationOutcome,
    SettlementDetail,
    UnknownReservationError,
)
from gateway.application.ports.money import Money

ORG_A = uuid4()
ORG_B = uuid4()


def _money(amount: str, currency: str = "USD") -> Money:
    return Money(Decimal(amount), currency)


def _detail(total: str) -> SettlementDetail:
    cost = _money(total)
    return SettlementDetail(
        provider="fake",
        model="fake-model",
        prompt_tokens=10,
        completion_tokens=5,
        input_cost=cost,
        output_cost=_money("0"),
        total_cost=cost,
    )


# ------------------------------------------------------------------ reservation outcomes


async def test_reserve_with_no_budget_configured_is_unbounded() -> None:
    ledger = InMemoryBudgetLedger()

    result = await ledger.reserve(ORG_A, "corr-1", _money("1000000"))

    assert result.outcome is ReservationOutcome.RESERVED
    assert result.permitted is True


async def test_reserve_within_budget_succeeds() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})

    result = await ledger.reserve(ORG_A, "corr-1", _money("50"))

    assert result.outcome is ReservationOutcome.RESERVED


async def test_reserve_exceeding_budget_is_denied() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("90"))

    result = await ledger.reserve(ORG_A, "corr-2", _money("20"))

    assert result.outcome is ReservationOutcome.EXCEEDED
    assert result.permitted is False
    assert result.remaining == _money("10")


async def test_exact_boundary_reservation_equal_to_remaining_is_allowed() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("90"))

    result = await ledger.reserve(ORG_A, "corr-2", _money("10"))

    assert result.outcome is ReservationOutcome.RESERVED


async def test_reserve_is_idempotent_for_the_same_correlation_id() -> None:
    """A retried reserve() call must not double-hold budget."""
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})

    first = await ledger.reserve(ORG_A, "corr-1", _money("60"))
    second = await ledger.reserve(ORG_A, "corr-1", _money("60"))

    assert first.outcome is second.outcome is ReservationOutcome.RESERVED
    # A second, different reservation must still see only ONE 60 held, not two.
    result = await ledger.reserve(ORG_A, "corr-2", _money("40"))
    assert result.outcome is ReservationOutcome.RESERVED


async def test_two_tenants_may_independently_reuse_the_same_correlation_id() -> None:
    """correlation_id is tenant-scoped identity, not globally unique (ADR-0017)."""
    ledger = InMemoryBudgetLedger({ORG_A: _money("100"), ORG_B: _money("100")})

    result_a = await ledger.reserve(ORG_A, "shared-id", _money("50"))
    result_b = await ledger.reserve(ORG_B, "shared-id", _money("50"))

    assert result_a.outcome is ReservationOutcome.RESERVED
    assert result_b.outcome is ReservationOutcome.RESERVED


# ------------------------------------------------------------------ settle / release


async def test_settle_books_actual_cost_and_releases_the_hold() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("60"))

    await ledger.settle(ORG_A, "corr-1", _detail("55"))

    # The 5 slack between estimate and actual is freed - a new reservation for 45 now fits.
    result = await ledger.reserve(ORG_A, "corr-2", _money("45"))
    assert result.outcome is ReservationOutcome.RESERVED


async def test_settle_is_idempotent() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("60"))

    await ledger.settle(ORG_A, "corr-1", _detail("60"))
    await ledger.settle(ORG_A, "corr-1", _detail("60"))  # must not double-book spend

    result = await ledger.reserve(ORG_A, "corr-2", _money("40"))
    assert result.outcome is ReservationOutcome.RESERVED  # not EXCEEDED, so spend wasn't doubled


async def test_settle_unknown_correlation_id_raises() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})

    with pytest.raises(UnknownReservationError):
        await ledger.settle(ORG_A, "never-reserved", _detail("10"))


async def test_release_frees_the_reservation_without_booking_spend() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("90"))

    await ledger.release(ORG_A, "corr-1")

    result = await ledger.reserve(ORG_A, "corr-2", _money("90"))
    assert result.outcome is ReservationOutcome.RESERVED


async def test_release_is_idempotent() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("90"))

    await ledger.release(ORG_A, "corr-1")
    await ledger.release(ORG_A, "corr-1")  # must not raise or double-adjust

    result = await ledger.reserve(ORG_A, "corr-2", _money("90"))
    assert result.outcome is ReservationOutcome.RESERVED


async def test_release_unknown_correlation_id_raises() -> None:
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})

    with pytest.raises(UnknownReservationError):
        await ledger.release(ORG_A, "never-reserved")


# ------------------------------------------------------------------ fail-closed


async def test_unavailable_store_fails_closed_on_reserve() -> None:
    ledger = InMemoryBudgetLedger(unavailable=True)

    with pytest.raises(LedgerUnavailableError):
        await ledger.reserve(ORG_A, "corr-1", _money("10"))


async def test_reserving_again_after_release_genuinely_re_holds_the_budget() -> None:
    """Parity with SqlBudgetLedger's Slice-11 regression fix: a released reservation must be
    re-held, not replayed as a phantom hold that leaves the full limit reservable."""
    ledger = InMemoryBudgetLedger({ORG_A: _money("100")})
    await ledger.reserve(ORG_A, "corr-1", _money("60"))
    await ledger.release(ORG_A, "corr-1")

    again = await ledger.reserve(ORG_A, "corr-1", _money("60"))

    assert again.outcome is ReservationOutcome.RESERVED
    competing = await ledger.reserve(ORG_A, "corr-2", _money("100"))
    assert competing.outcome is ReservationOutcome.EXCEEDED
