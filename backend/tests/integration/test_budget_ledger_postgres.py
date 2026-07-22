"""SqlBudgetLedger tests against real PostgreSQL (ADR-0017, ADR-0016 Slice 9).

Runs in Gate 2 / CI (skipped only when no Postgres URL is configured). Per ADR-0014 the
connection is the least-privilege ``app_rw`` role. These are the claims that can only be proven
against a real database, never against ``InMemoryBudgetLedger``: atomic reservation under genuine
concurrent connections, tenant isolation via RLS, a durable idempotency constraint, monetary
precision round-tripping through PostgreSQL ``numeric``, and append-only enforcement by grant.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from gateway.adapters.ledger.sql_budget_ledger import SqlBudgetLedger
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.ports.ledger import (
    LedgerUnavailableError,
    ReservationOutcome,
    SettlementDetail,
    UnknownReservationError,
)
from gateway.application.ports.money import Money
from tests.support.postgres import PG_URL, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


def _money(amount: str, currency: str = "USD") -> Money:
    return Money(Decimal(amount), currency)


def _detail(total: str) -> SettlementDetail:
    cost = _money(total)
    return SettlementDetail(
        provider="openai",
        model="gpt-4o",
        prompt_tokens=10,
        completion_tokens=5,
        input_cost=cost,
        output_cost=_money("0"),
        total_cost=cost,
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def ledger(engine: AsyncEngine) -> SqlBudgetLedger:
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    return SqlBudgetLedger(factory)


async def _seed_org(engine: AsyncEngine, org_id: UUID) -> None:
    """Insert an organization (not RLS-scoped) - the FK parent for its budget."""
    slug = f"t-{org_id.hex[:16]}"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org_id), "slug": slug, "name": f"tenant-{slug}"},
        )


async def _seed_budget(
    engine: AsyncEngine, org_id: UUID, limit: str, currency: str = "USD"
) -> None:
    """org_budget is RLS-scoped, so the insert must run with its tenant context bound -
    same reasoning as test_auth_rls_postgres.py's ``_seed_credential``."""
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO org_budget (organization_id, amount_limit, currency) "
                "VALUES (:org, :limit, :currency)"
            ),
            {"org": str(org_id), "limit": limit, "currency": currency},
        )
        await uow.commit()


async def _org_budget_row(engine: AsyncEngine, org_id: UUID) -> dict[str, Decimal]:
    """Tenant-bound read of org_budget's totals (RLS-scoped, like the insert above)."""
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    async with factory(tenant_id=org_id) as uow:
        row = (
            (
                await uow.session.execute(
                    text("SELECT reserved, spent FROM org_budget WHERE organization_id = :org"),
                    {"org": str(org_id)},
                )
            )
            .mappings()
            .one()
        )
        await uow.commit()
    return {"reserved": Decimal(row["reserved"]), "spent": Decimal(row["spent"])}


@pytest.fixture
async def org(engine: AsyncEngine) -> UUID:
    org_id = uuid4()
    await _seed_org(engine, org_id)
    return org_id


# ------------------------------------------------------------------ reservation outcomes


async def test_reserve_within_budget_succeeds(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "100")

    result = await ledger.reserve(org, "corr-1", _money("40"))

    assert result.outcome is ReservationOutcome.RESERVED


async def test_reserve_exceeding_budget_is_denied(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "100")
    await ledger.reserve(org, "corr-1", _money("90"))

    result = await ledger.reserve(org, "corr-2", _money("20"))

    assert result.outcome is ReservationOutcome.EXCEEDED
    assert result.remaining == _money("10")


async def test_exact_boundary_reservation_is_allowed(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "100")
    await ledger.reserve(org, "corr-1", _money("90"))

    result = await ledger.reserve(org, "corr-2", _money("10"))

    assert result.outcome is ReservationOutcome.RESERVED


async def test_reserve_with_no_budget_row_is_unbounded(ledger: SqlBudgetLedger, org: UUID) -> None:
    result = await ledger.reserve(org, "corr-1", _money("1000000"))

    assert result.outcome is ReservationOutcome.RESERVED


# ------------------------------------------------------------------ idempotency (real constraint)


async def test_duplicate_reservation_is_idempotent_not_double_held(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "100")

    first = await ledger.reserve(org, "corr-1", _money("60"))
    second = await ledger.reserve(org, "corr-1", _money("60"))

    assert first.outcome is second.outcome is ReservationOutcome.RESERVED
    # If the retry had reserved a second time, only 100-60-60<0 would remain - this must still fit.
    third = await ledger.reserve(org, "corr-2", _money("40"))
    assert third.outcome is ReservationOutcome.RESERVED


async def test_duplicate_settlement_does_not_double_book_spend(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "100")
    await ledger.reserve(org, "corr-1", _money("60"))

    await ledger.settle(org, "corr-1", _detail("55"))
    await ledger.settle(org, "corr-1", _detail("55"))  # must be a no-op, not a second charge

    # Only one 55 should have been spent; a reservation of 40 should still fit (100-55=45>=40).
    result = await ledger.reserve(org, "corr-2", _money("40"))
    assert result.outcome is ReservationOutcome.RESERVED


async def test_settle_unknown_correlation_id_raises(ledger: SqlBudgetLedger, org: UUID) -> None:
    with pytest.raises(UnknownReservationError):
        await ledger.settle(org, "never-reserved", _detail("10"))


async def test_release_then_settle_is_rejected_as_a_defect(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    """Settling a released reservation is a caller defect, not a silent no-op or a double
    booking."""
    await _seed_budget(engine, org, "100")
    await ledger.reserve(org, "corr-1", _money("60"))
    await ledger.release(org, "corr-1")

    with pytest.raises(UnknownReservationError):
        await ledger.settle(org, "corr-1", _detail("60"))


async def test_release_of_an_already_settled_reservation_is_a_safe_no_op(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    """release() must never alter a committed reservation's status or re-adjust org_budget -
    committed is a terminal state release() treats as an idempotent no-op, not a downgrade."""
    await _seed_budget(engine, org, "100")
    await ledger.reserve(org, "corr-1", _money("60"))
    await ledger.settle(org, "corr-1", _detail("55"))

    await ledger.release(org, "corr-1")  # must not raise, and must not touch spent/reserved again

    row = await _org_budget_row(engine, org)
    assert row["spent"] == Decimal("55")  # unchanged by the release() call
    assert row["reserved"] == Decimal("0")  # already released by settle(), not decremented again


# ------------------------------------------------------------------ concurrency (real Postgres)


async def test_two_requests_racing_for_the_last_budget_only_one_succeeds(
    engine: AsyncEngine, org: UUID
) -> None:
    """The property InMemoryBudgetLedger cannot prove: genuine concurrent connections racing the
    same atomic UPDATE. Only one of two simultaneous reservations for 60 against a 100 budget may
    succeed."""
    await _seed_budget(engine, org, "100")
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    ledger_a = SqlBudgetLedger(factory)
    ledger_b = SqlBudgetLedger(factory)

    results = await asyncio.gather(
        ledger_a.reserve(org, "concurrent-1", _money("60")),
        ledger_b.reserve(org, "concurrent-2", _money("60")),
    )

    outcomes = sorted(r.outcome.value for r in results)
    assert outcomes == ["exceeded", "reserved"]


async def test_concurrent_reservations_never_exceed_the_budget_total(
    engine: AsyncEngine, org: UUID
) -> None:
    """A stronger version of the race test: N concurrent attempts against a budget that fits
    exactly M of them must admit exactly M, regardless of scheduling order."""
    await _seed_budget(engine, org, "50")
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    ledgers = [SqlBudgetLedger(factory) for _ in range(10)]

    results = await asyncio.gather(
        *(ledgers[i].reserve(org, f"race-{i}", _money("10")) for i in range(10))
    )

    reserved_count = sum(1 for r in results if r.outcome is ReservationOutcome.RESERVED)
    assert reserved_count == 5  # exactly 50 / 10 fit, never more


async def test_concurrent_duplicate_reservation_never_double_holds_budget(
    engine: AsyncEngine, org: UUID
) -> None:
    """Two concurrent reserve() calls for the SAME never-before-seen correlation_id (a genuine
    duplicate-request race, not a sequential retry) must resolve to exactly one held reservation,
    recovering from the UNIQUE(organization_id, correlation_id) conflict rather than corrupting
    org_budget.reserved or leaking a second row."""
    await _seed_budget(engine, org, "100")
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    ledger_a = SqlBudgetLedger(factory)
    ledger_b = SqlBudgetLedger(factory)

    results = await asyncio.gather(
        ledger_a.reserve(org, "same-corr-id", _money("60")),
        ledger_b.reserve(org, "same-corr-id", _money("60")),
    )

    assert all(r.outcome is ReservationOutcome.RESERVED for r in results)
    # If 60 had been held twice, only 100-120<0 would remain; a fresh 40 must still fit exactly.
    row = await _org_budget_row(engine, org)
    assert row["reserved"] == Decimal("60")
    third = await ledger_a.reserve(org, "another-corr-id", _money("40"))
    assert third.outcome is ReservationOutcome.RESERVED


async def test_concurrent_settlement_of_the_same_reservation_never_double_charges(
    engine: AsyncEngine, org: UUID
) -> None:
    """The defect this test guards: settle()'s status check must lock the reservation row
    (SELECT ... FOR UPDATE), or two concurrent settle() calls for the same correlation_id could
    both read status="reserved" before either commits and both book spend - status would still
    end up "committed" (looking idempotent) while spend was booked twice."""
    await _seed_budget(engine, org, "100")
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    ledger_a = SqlBudgetLedger(factory)
    ledger_b = SqlBudgetLedger(factory)
    await ledger_a.reserve(org, "corr-1", _money("60"))

    await asyncio.gather(
        ledger_a.settle(org, "corr-1", _detail("55")),
        ledger_b.settle(org, "corr-1", _detail("55")),
    )

    row = await _org_budget_row(engine, org)
    assert row["spent"] == Decimal("55")  # not 110 - the race must not double-book
    assert row["reserved"] == Decimal("0")


# ------------------------------------------------------------------ tenant isolation (RLS)


async def test_cross_tenant_reservation_lookup_is_isolated_by_rls(
    engine: AsyncEngine, ledger: SqlBudgetLedger
) -> None:
    org_a, org_b = uuid4(), uuid4()
    await _seed_org(engine, org_a)
    await _seed_org(engine, org_b)
    await _seed_budget(engine, org_a, "100")
    await _seed_budget(engine, org_b, "100")

    await ledger.reserve(org_a, "shared-corr-id", _money("30"))
    # Org B reserving under the SAME correlation_id must be treated as a NEW reservation, not the
    # idempotent replay of org A's - composite (organization_id, correlation_id) identity, enforced
    # by RLS scoping org B's view to its own rows only.
    result_b = await ledger.reserve(org_b, "shared-corr-id", _money("30"))

    assert result_b.outcome is ReservationOutcome.RESERVED
    # Org A's own reservation must still show only one 30 held, not affected by org B's.
    exceeded = await ledger.reserve(org_a, "another-corr-id", _money("75"))
    assert exceeded.outcome is ReservationOutcome.EXCEEDED  # 100-30=70 remaining, 75 doesn't fit


async def test_rls_prevents_settling_a_reservation_through_the_wrong_tenant(
    engine: AsyncEngine, ledger: SqlBudgetLedger
) -> None:
    """RLS filters ``budget_reservation`` by ``organization_id`` on every query this adapter
    issues. A reservation created under org A's tenant context must be invisible when the SAME
    ``correlation_id`` is looked up under org B's - settle() must see "never reserved" (RLS
    returning zero rows), never org A's row, and never a cross-tenant charge."""
    org_a, org_b = uuid4(), uuid4()
    await _seed_org(engine, org_a)
    await _seed_org(engine, org_b)
    await _seed_budget(engine, org_a, "100")

    await ledger.reserve(org_a, "corr-shared", _money("40"))

    with pytest.raises(UnknownReservationError):
        await ledger.settle(org_b, "corr-shared", _detail("40"))


# ------------------------------------------------------------------ monetary precision


async def test_fractional_cost_round_trips_exactly_through_numeric_18_8(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "1000")
    tricky = _money("0.00000001")  # smallest representable unit at 8 decimal places

    result = await ledger.reserve(org, "corr-1", tricky)
    assert result.outcome is ReservationOutcome.RESERVED

    await ledger.settle(org, "corr-1", _detail("0.00000001"))

    row = await _org_budget_row(engine, org)
    assert row["spent"] == Decimal("0.00000001")


async def test_maximum_precision_amount_does_not_lose_a_digit(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    await _seed_budget(engine, org, "100000000.00000000")
    precise = _money("12345678.87654321")

    result = await ledger.reserve(org, "corr-1", precise)

    assert result.outcome is ReservationOutcome.RESERVED
    row = await _org_budget_row(engine, org)
    assert row["reserved"] == Decimal("12345678.87654321")


# ------------------------------------------------------------------ append-only enforcement


async def test_cost_ledger_rejects_update_from_the_runtime_role(
    engine: AsyncEngine, ledger: SqlBudgetLedger, org: UUID
) -> None:
    """app_rw must not be able to mutate a settled cost record (migration 0006's REVOKE)."""
    await _seed_budget(engine, org, "100")
    await ledger.reserve(org, "corr-1", _money("40"))
    await ledger.settle(org, "corr-1", _detail("40"))

    with pytest.raises(DBAPIError, match="permission denied"):
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE cost_ledger SET total_cost = 0 WHERE organization_id = :org"),
                {"org": str(org)},
            )


# ------------------------------------------------------------------ fail-closed on outage


async def test_unreachable_store_fails_closed() -> None:
    broken_engine = create_async_engine("postgresql+asyncpg://nouser:nopass@localhost:1/nodb")
    factory = UnitOfWorkFactory(create_session_factory(broken_engine), rls_enabled=True)
    ledger = SqlBudgetLedger(factory)
    try:
        with pytest.raises(LedgerUnavailableError):
            await ledger.reserve(uuid4(), "corr-1", _money("10"))
    finally:
        await broken_engine.dispose()
