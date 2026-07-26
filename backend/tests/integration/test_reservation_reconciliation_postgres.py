"""Reservation reconciliation against real PostgreSQL (Phase 5 M2).

The crash-safety debt Slice 9 left open: a hold whose owner died stayed ``reserved`` forever, so a
crash-looping deployment silently consumed a tenant's budget with nothing to report it.

**These are the claims that only a real database can support.** ``InMemoryBudgetLedger`` can show
that the *contract* holds in one process; it cannot show that two reconcilers running on two
connections do not both reclaim the same hold, that a reconciler racing a settlement does not let
the pair credit the tenant twice, or that RLS confines a sweep to one tenant. Every test here
therefore uses genuine concurrent connections as the least-privilege ``app_rw`` role (ADR-0014),
and the money assertions read ``org_budget`` directly rather than trusting a return value.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.ledger.sql_budget_ledger import SqlBudgetLedger
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.ports.ledger import ReservationOutcome, SettlementDetail
from gateway.application.ports.money import Money
from tests.support.postgres import PG_URL, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]

#: Any cutoff later than "now" makes every live hold look stale, which is exactly what a test
#: wants: it can reclaim deterministically without waiting for a real TTL to elapse.
FUTURE = datetime.now(UTC) + timedelta(days=1)
PAST = datetime.now(UTC) - timedelta(days=1)


def _money(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


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


def _ledger(engine: AsyncEngine) -> SqlBudgetLedger:
    return SqlBudgetLedger(UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True))


async def _seed(engine: AsyncEngine, org_id: UUID, limit: str = "1000.00") -> None:
    slug = f"rec-{org_id.hex[:16]}"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org_id), "slug": slug, "name": f"tenant-{slug}"},
        )
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO org_budget (organization_id, amount_limit, currency) "
                "VALUES (:org, :limit, 'USD')"
            ),
            {"org": str(org_id), "limit": limit},
        )
        await uow.commit()


async def _budget(engine: AsyncEngine, org_id: UUID) -> dict[str, Decimal]:
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
    return {"reserved": row["reserved"], "spent": row["spent"]}


async def _status(engine: AsyncEngine, org_id: UUID, correlation_id: str) -> str:
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    async with factory(tenant_id=org_id) as uow:
        value = (
            await uow.session.execute(
                text(
                    "SELECT status FROM budget_reservation "
                    "WHERE organization_id = :org AND correlation_id = :cid"
                ),
                {"org": str(org_id), "cid": correlation_id},
            )
        ).scalar_one()
    return str(value)


# ------------------------------------------------------------------ do no harm


async def test_a_fresh_hold_is_left_alone(engine: AsyncEngine) -> None:
    """The dangerous direction. A hold younger than the cutoff belongs to a request that may
    still be running; reclaiming it would let the tenant reserve the same money twice."""
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "live", _money("10.00"))

    assert await ledger.reconcile_expired(org, older_than=PAST) == 0

    assert (await _budget(engine, org))["reserved"] == Decimal("10.00000000")
    assert await _status(engine, org, "live") == "reserved"


async def test_settled_and_released_holds_are_left_alone(engine: AsyncEngine) -> None:
    """Their money already moved. Reclaiming either would credit the tenant a second time."""
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "settled", _money("10.00"))
    await ledger.settle(org, "settled", _detail("4.00"))
    await ledger.reserve(org, "released", _money("10.00"))
    await ledger.release(org, "released")

    assert await ledger.reconcile_expired(org, older_than=FUTURE) == 0

    budget = await _budget(engine, org)
    assert budget["reserved"] == Decimal("0")
    assert budget["spent"] == Decimal("4.00000000")


async def test_a_sweep_cannot_see_or_touch_another_tenants_holds(engine: AsyncEngine) -> None:
    """Tenant isolation is what lets this run as ``app_rw`` under FORCE RLS rather than needing a
    privileged cross-tenant sweep (ADR-0014, and ADR-0019's rule that any further SECURITY
    DEFINER needs its own ADR). Proven against real RLS, not inferred from the signature."""
    mine, theirs = uuid4(), uuid4()
    await _seed(engine, mine)
    await _seed(engine, theirs)
    ledger = _ledger(engine)
    await ledger.reserve(mine, "mine", _money("10.00"))
    await ledger.reserve(theirs, "theirs", _money("10.00"))

    reclaimed = await ledger.reconcile_expired(mine, older_than=FUTURE)

    assert reclaimed == 1
    assert (await _budget(engine, mine))["reserved"] == Decimal("0")
    assert (await _budget(engine, theirs))["reserved"] == Decimal("10.00000000")
    assert await _status(engine, theirs, "theirs") == "reserved"


# ------------------------------------------------------------------ reclaim what is dead


async def test_a_stale_hold_is_reclaimed_and_the_budget_returned(engine: AsyncEngine) -> None:
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "abandoned", _money("25.00"))

    assert await ledger.reconcile_expired(org, older_than=FUTURE) == 1

    budget = await _budget(engine, org)
    assert budget["reserved"] == Decimal("0")
    assert budget["spent"] == Decimal("0")
    assert await _status(engine, org, "abandoned") == "expired"


async def test_repeated_reconciliation_is_idempotent(engine: AsyncEngine) -> None:
    """A second sweep must reclaim nothing. If it reclaimed the same hold again, ``reserved``
    would go negative and violate ``org_budget_reserved_ck``."""
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "abandoned", _money("25.00"))

    first = await ledger.reconcile_expired(org, older_than=FUTURE)
    second = await ledger.reconcile_expired(org, older_than=FUTURE)

    assert (first, second) == (1, 0)
    assert (await _budget(engine, org))["reserved"] == Decimal("0")


async def test_many_stale_holds_are_reclaimed_in_one_atomic_sweep(engine: AsyncEngine) -> None:
    org = uuid4()
    await _seed(engine, org, limit="1000.00")
    ledger = _ledger(engine)
    for index in range(5):
        await ledger.reserve(org, f"dead-{index}", _money("10.00"))
    assert (await _budget(engine, org))["reserved"] == Decimal("50.00000000")

    assert await ledger.reconcile_expired(org, older_than=FUTURE) == 5

    assert (await _budget(engine, org))["reserved"] == Decimal("0")


# ------------------------------------------------------------------ concurrency, for real


async def test_two_concurrent_reconcilers_do_not_double_release(engine: AsyncEngine) -> None:
    """Genuine concurrent connections, not two calls in one event loop. ``FOR UPDATE SKIP
    LOCKED`` must give each sweep a disjoint set: between them they reclaim each hold exactly
    once, and ``reserved`` lands on zero rather than on a negative number the CHECK would reject.
    """
    org = uuid4()
    await _seed(engine, org, limit="1000.00")
    for index in range(10):
        await _ledger(engine).reserve(org, f"dead-{index}", _money("10.00"))
    assert (await _budget(engine, org))["reserved"] == Decimal("100.00000000")

    left, right = await asyncio.gather(
        _ledger(engine).reconcile_expired(org, older_than=FUTURE),
        _ledger(engine).reconcile_expired(org, older_than=FUTURE),
    )

    assert left + right == 10, "each hold must be reclaimed by exactly one of the two sweeps"
    assert (await _budget(engine, org))["reserved"] == Decimal("0")


async def test_reconciliation_racing_settlement_never_double_counts(engine: AsyncEngine) -> None:
    """The interleaving that would lose the operator money. Whichever wins, the hold must leave
    ``reserved`` exactly once and the spend must be booked exactly once."""
    org = uuid4()
    await _seed(engine, org, limit="1000.00")
    await _ledger(engine).reserve(org, "racing", _money("10.00"))

    await asyncio.gather(
        _ledger(engine).reconcile_expired(org, older_than=FUTURE),
        _ledger(engine).settle(org, "racing", _detail("4.00")),
    )

    budget = await _budget(engine, org)
    assert budget["reserved"] == Decimal("0"), "the hold was returned exactly once"
    assert budget["spent"] == Decimal("4.00000000"), "the real spend was booked exactly once"


async def test_a_late_settlement_after_expiry_books_spend_without_double_crediting(
    engine: AsyncEngine,
) -> None:
    """Sequential and unambiguous, unlike the race above. The tokens were consumed, so the spend
    is booked; the hold is already back, so it must not be returned again - which at this
    boundary would drive ``reserved`` below zero and raise a constraint violation instead."""
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "slow", _money("10.00"))
    assert await ledger.reconcile_expired(org, older_than=FUTURE) == 1
    assert (await _budget(engine, org))["reserved"] == Decimal("0")

    await ledger.settle(org, "slow", _detail("4.00"))

    budget = await _budget(engine, org)
    assert budget["reserved"] == Decimal("0")
    assert budget["spent"] == Decimal("4.00000000")
    assert await _status(engine, org, "slow") == "committed"


async def test_releasing_an_expired_hold_is_an_idempotent_no_op(engine: AsyncEngine) -> None:
    """A request that finally notices its provider failed, after its hold was already reclaimed."""
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "late-release", _money("10.00"))
    await ledger.reconcile_expired(org, older_than=FUTURE)

    await ledger.release(org, "late-release")

    assert (await _budget(engine, org))["reserved"] == Decimal("0")
    assert await _status(engine, org, "late-release") == "expired"


async def test_reserving_the_same_id_after_expiry_takes_a_real_hold_again(
    engine: AsyncEngine,
) -> None:
    """An ``expired`` row must not replay as RESERVED - that would report a hold while holding
    nothing, the phantom-hold defect Slice 11 found for ``released`` rows and that ``expired``
    reintroduced the moment reconciliation could write it."""
    org = uuid4()
    await _seed(engine, org)
    ledger = _ledger(engine)
    await ledger.reserve(org, "recycled", _money("10.00"))
    await ledger.reconcile_expired(org, older_than=FUTURE)

    again = await ledger.reserve(org, "recycled", _money("10.00"))

    assert again.outcome is ReservationOutcome.RESERVED
    assert (await _budget(engine, org))["reserved"] == Decimal("10.00000000")
    assert await _status(engine, org, "recycled") == "reserved"


async def test_an_org_with_no_budget_row_reconciles_without_error(engine: AsyncEngine) -> None:
    """No ``org_budget`` row means ``reserve`` never incremented anything, so the sweep must mark
    the reservation and adjust nothing - not fail trying to update a row that is not there."""
    org = uuid4()
    slug = f"rec-{org.hex[:16]}"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org), "slug": slug, "name": f"tenant-{slug}"},
        )
    ledger = _ledger(engine)
    await ledger.reserve(org, "unbounded", _money("10.00"))

    assert await ledger.reconcile_expired(org, older_than=FUTURE) == 1
    assert await _status(engine, org, "unbounded") == "expired"


async def test_an_unreachable_database_fails_closed_rather_than_reporting_a_clean_sweep() -> None:
    """A sweep that could not run must say so, not return 0 as if there had been nothing to
    reclaim. The reconciler above it is what decides that a failed repair is survivable; the port
    must not make that decision for it by fabricating a result."""
    from gateway.application.ports.ledger import LedgerUnavailableError

    unreachable = create_database_engine(
        url="postgresql+asyncpg://app_rw:app_rw@127.0.0.1:1/gateway"
    )
    try:
        ledger = SqlBudgetLedger(
            UnitOfWorkFactory(create_session_factory(unreachable), rls_enabled=True)
        )
        with pytest.raises(LedgerUnavailableError):
            await ledger.reconcile_expired(uuid4(), older_than=FUTURE)
    finally:
        await unreachable.dispose()
