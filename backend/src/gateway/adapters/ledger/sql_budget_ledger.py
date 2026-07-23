"""PostgreSQL-transactional BudgetLedgerPort (ADR-0017, ADR-0016 Slice 9).

``reserve``'s budget check is a single conditional ``UPDATE ... WHERE (limit - spent - reserved)
>= :cost RETURNING`` - one indivisible read-check-write statement, exactly the property ADR-0004
wanted from a Redis Lua script, provided here by PostgreSQL's own row-level locking instead. No
explicit ``SELECT ... FOR UPDATE`` is needed for that statement: an ``UPDATE``'s ``WHERE`` clause
already locks the row it matches before evaluating whether to write it, so two concurrent
``reserve`` calls for *different* correlation ids against the same organization serialize on that
single statement - one succeeds, the other's ``WHERE`` re-evaluates against the now-updated row and
(correctly) may fail.

That statement alone is not sufficient for two concurrent ``reserve`` calls sharing the SAME
correlation id (a genuine duplicate-request race, not a sequential retry): both could pass the
"already reserved?" lookup below before either commits, and the loser's budget UPDATE would then
evaluate against the winner's *already-committed* reserved amount and see insufficient remaining
budget - reporting EXCEEDED for what is actually its own already-satisfied duplicate request, not
a competing one. ``reserve`` therefore opens by taking a transaction-scoped PostgreSQL advisory
lock keyed on ``(organization_id, correlation_id)`` (there is no row to lock yet, so a row lock
cannot serve this purpose) - the second caller blocks until the first fully commits, then correctly
finds the existing reservation and replays it idempotently.

The idempotent-replay branch covers a *live* (``reserved``) or already-settled (``committed``) row
only. A ``released`` row is deliberately excluded and re-activated instead (``_hold``): its hold was
already returned to the budget, so replaying it would report ``RESERVED`` while holding nothing -
a phantom hold leaving the full limit reservable by someone else. Found in Slice 11 while analysing
retry semantics; reachable from Slice 10's coordinator today (reserve -> provider fails -> release
-> the same ``correlation_id`` is submitted again), so it is a fix, not a retry-only accommodation.

``settle`` and ``release`` are a different shape - branch-on-status, not a single conditional
write - so each locks its ``budget_reservation`` row explicitly with ``SELECT ... FOR UPDATE``
before reading ``status``. Without it, two concurrent calls for the same ``correlation_id`` could
both read ``status="reserved"`` before either commits and both apply their own budget update -
``budget_reservation.status`` would still end up correctly ``"committed"``, but the monetary
side-effect would have run twice. The lock makes the second caller block until the first commits,
then re-read the now-``"committed"``/``"released"`` row and take the idempotent no-op path.

Every method opens its own ``AsyncUnitOfWork`` (RLS-bound to ``organization_id``) and commits or
rolls back within itself - this port's callers do not participate in an ambient transaction, so
each operation is one complete unit of work, matching how ``AsyncUnitOfWork`` is used everywhere
else in this codebase.

Any unexpected database error (lost connection, deadlock, etc.) is translated to
``LedgerUnavailableError`` - fail closed (ADR-0009 row 1). A currency mismatch between the
estimated/actual cost and the org's configured budget currency is a **configuration defect**,
reusing ``UnsupportedCurrencyError`` from ``application/ports/budget.py`` (the same fact
``BudgetEnforcer`` already guards - Rule 3: one shared concept, one shared exception type).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import RowMapping, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.adapters.persistence.ledger_tables import budget_reservation, cost_ledger, org_budget
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.ports.budget import UnsupportedCurrencyError
from gateway.application.ports.ledger import (
    BudgetLedgerPort,
    LedgerUnavailableError,
    ReservationOutcome,
    ReservationResult,
    SettlementDetail,
    UnknownReservationError,
)
from gateway.application.ports.money import Money

_RELEASED = "released"
_COMMITTED = "committed"
_TERMINAL_STATUSES = (_COMMITTED, _RELEASED)


class SqlBudgetLedger(BudgetLedgerPort):
    """Durable, tenant-scoped, atomic reserve/commit/release against real PostgreSQL."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    @staticmethod
    async def _hold(
        session: AsyncSession,
        existing: RowMapping | None,
        organization_id: UUID,
        correlation_id: str,
        estimated_cost: Money,
    ) -> None:
        """Record the hold: insert a fresh reservation, or re-activate a previously RELEASED one.

        A released row must be re-activated rather than left alone, because ``reserve``'s
        idempotent-replay branch deliberately does not cover it: its hold was already returned to
        the budget, so replaying it would report RESERVED while holding nothing (a phantom hold
        that leaves the full limit reservable by someone else - see the Slice-11 evidence record).
        The advisory lock taken at the top of ``reserve`` serializes concurrent callers on this
        exact key, so the read-then-write here cannot race another reservation of the same id.
        """
        if existing is None:
            await session.execute(
                insert(budget_reservation).values(
                    id=uuid4(),
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    estimated_cost=estimated_cost.amount,
                    currency=estimated_cost.currency,
                    status="reserved",
                )
            )
            return
        await session.execute(
            update(budget_reservation)
            .where(budget_reservation.c.id == existing["id"])
            .values(
                status="reserved",
                estimated_cost=estimated_cost.amount,
                currency=estimated_cost.currency,
                actual_cost=None,
                settled_at=None,
            )
        )

    async def reserve(
        self, organization_id: UUID, correlation_id: str, estimated_cost: Money
    ) -> ReservationResult:
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                session = uow.session

                # Advisory lock keyed on (organization_id, correlation_id) - not a row lock,
                # because no budget_reservation row exists yet to lock. Without this, two
                # concurrent reserve() calls for the SAME new correlation_id could both pass the
                # "existing is None" check below; the loser's atomic budget UPDATE would then
                # evaluate against the winner's *already-committed* reserved amount and see
                # insufficient remaining budget (EXCEEDED) even though this is actually its own
                # already-satisfied duplicate request, not a competing one. The lock is
                # transaction-scoped (auto-released on commit/rollback) and serializes only calls
                # sharing this exact key, not all reservations for the organization.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:org), hashtext(:cid))"),
                    {"org": str(organization_id), "cid": correlation_id},
                )

                existing = (
                    (
                        await session.execute(
                            select(
                                budget_reservation.c.id,
                                budget_reservation.c.estimated_cost,
                                budget_reservation.c.currency,
                                budget_reservation.c.status,
                            ).where(
                                budget_reservation.c.organization_id == organization_id,
                                budget_reservation.c.correlation_id == correlation_id,
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                if existing is not None and existing["status"] != _RELEASED:
                    await uow.commit()
                    # Idempotent replay: the original decision stands, never re-evaluated. Only
                    # a *live* ("reserved") or already-settled ("committed") row replays - a
                    # RELEASED row is deliberately excluded and falls through to be re-held
                    # below, because its hold was already given back to the budget.
                    return ReservationResult(
                        outcome=ReservationOutcome.RESERVED,
                        organization_id=organization_id,
                        correlation_id=correlation_id,
                        estimated_cost=Money(existing["estimated_cost"], existing["currency"]),
                    )

                budget_row = (
                    (
                        await session.execute(
                            select(
                                org_budget.c.amount_limit,
                                org_budget.c.spent,
                                org_budget.c.reserved,
                                org_budget.c.currency,
                            ).where(org_budget.c.organization_id == organization_id)
                        )
                    )
                    .mappings()
                    .first()
                )

                if budget_row is None:
                    # No budget configured for this org - ordinary, allowed, unbounded (Slice 8's
                    # BudgetPort.snapshot()->None posture, carried over here).
                    await self._hold(
                        session, existing, organization_id, correlation_id, estimated_cost
                    )
                    await uow.commit()
                    return ReservationResult(
                        outcome=ReservationOutcome.RESERVED,
                        organization_id=organization_id,
                        correlation_id=correlation_id,
                        estimated_cost=estimated_cost,
                    )

                if estimated_cost.currency != budget_row["currency"]:
                    raise UnsupportedCurrencyError(
                        f"cost currency {estimated_cost.currency!r} does not match budget "
                        f"currency {budget_row['currency']!r} for organization {organization_id}"
                    )

                # The atomic primitive: one UPDATE, gated by its own WHERE clause. Two concurrent
                # reserve() calls for the same org serialize here - only one can see remaining
                # budget cover its own cost.
                updated = (
                    await session.execute(
                        update(org_budget)
                        .where(
                            org_budget.c.organization_id == organization_id,
                            (org_budget.c.amount_limit - org_budget.c.spent - org_budget.c.reserved)
                            >= estimated_cost.amount,
                        )
                        .values(reserved=org_budget.c.reserved + estimated_cost.amount)
                        .returning(org_budget.c.organization_id)
                    )
                ).first()

                if updated is None:
                    remaining = Money(
                        budget_row["amount_limit"] - budget_row["spent"] - budget_row["reserved"],
                        budget_row["currency"],
                    )
                    await uow.rollback()
                    return ReservationResult(
                        outcome=ReservationOutcome.EXCEEDED,
                        organization_id=organization_id,
                        correlation_id=correlation_id,
                        estimated_cost=estimated_cost,
                        remaining=remaining,
                    )

                await self._hold(session, existing, organization_id, correlation_id, estimated_cost)
                await uow.commit()
                return ReservationResult(
                    outcome=ReservationOutcome.RESERVED,
                    organization_id=organization_id,
                    correlation_id=correlation_id,
                    estimated_cost=estimated_cost,
                )
        except (UnsupportedCurrencyError, LedgerUnavailableError):
            raise
        except (SQLAlchemyError, OSError) as exc:
            # OSError covers a raw connection refusal (e.g. ConnectionRefusedError) that can
            # surface unwrapped, before SQLAlchemy's own exception translation applies - a
            # database that refuses the TCP connection outright is exactly as unavailable as
            # one that accepts the connection and then errors (ADR-0009 row 1: either way,
            # fail closed, never propagate a raw infrastructure exception to the caller).
            raise LedgerUnavailableError(str(exc)) from exc

    async def settle(
        self, organization_id: UUID, correlation_id: str, detail: SettlementDetail
    ) -> None:
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                session = uow.session
                row = (
                    (
                        await session.execute(
                            select(
                                budget_reservation.c.id,
                                budget_reservation.c.status,
                                budget_reservation.c.estimated_cost,
                                budget_reservation.c.currency,
                            )
                            .where(
                                budget_reservation.c.organization_id == organization_id,
                                budget_reservation.c.correlation_id == correlation_id,
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    # Exception propagates out of `async with` - AsyncUnitOfWork.__aexit__
                    # rolls back automatically; no manual rollback needed here.
                    raise UnknownReservationError(
                        f"correlation_id={correlation_id!r} was never reserved for org "
                        f"{organization_id}"
                    )
                if row["status"] == "committed":
                    await uow.commit()
                    return  # idempotent replay - already settled, never double-book
                if row["status"] in _TERMINAL_STATUSES:
                    raise UnknownReservationError(
                        f"correlation_id={correlation_id!r} cannot be settled - reservation is "
                        f"already {row['status']!r}"
                    )
                if detail.total_cost.currency != row["currency"]:
                    raise UnsupportedCurrencyError(
                        f"actual cost currency {detail.total_cost.currency!r} does not match "
                        f"reservation currency {row['currency']!r} for correlation_id="
                        f"{correlation_id!r}"
                    )

                await session.execute(
                    update(org_budget)
                    .where(org_budget.c.organization_id == organization_id)
                    .values(
                        reserved=org_budget.c.reserved - row["estimated_cost"],
                        spent=org_budget.c.spent + detail.total_cost.amount,
                    )
                )
                await session.execute(
                    update(budget_reservation)
                    .where(budget_reservation.c.id == row["id"])
                    .values(
                        status="committed",
                        actual_cost=detail.total_cost.amount,
                        settled_at=func.now(),
                    )
                )
                await session.execute(
                    pg_insert(cost_ledger)
                    .values(
                        id=uuid4(),
                        organization_id=organization_id,
                        correlation_id=correlation_id,
                        provider=detail.provider,
                        model=detail.model,
                        prompt_tokens=detail.prompt_tokens,
                        completion_tokens=detail.completion_tokens,
                        input_cost=detail.input_cost.amount,
                        output_cost=detail.output_cost.amount,
                        total_cost=detail.total_cost.amount,
                        currency=detail.total_cost.currency,
                    )
                    .on_conflict_do_nothing(index_elements=["organization_id", "correlation_id"])
                )
                await uow.commit()
        except (UnsupportedCurrencyError, LedgerUnavailableError, UnknownReservationError):
            raise
        except (SQLAlchemyError, OSError) as exc:
            # OSError covers a raw connection refusal (e.g. ConnectionRefusedError) that can
            # surface unwrapped, before SQLAlchemy's own exception translation applies - a
            # database that refuses the TCP connection outright is exactly as unavailable as
            # one that accepts the connection and then errors (ADR-0009 row 1: either way,
            # fail closed, never propagate a raw infrastructure exception to the caller).
            raise LedgerUnavailableError(str(exc)) from exc

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                session = uow.session
                row = (
                    (
                        await session.execute(
                            select(
                                budget_reservation.c.id,
                                budget_reservation.c.status,
                                budget_reservation.c.estimated_cost,
                            )
                            .where(
                                budget_reservation.c.organization_id == organization_id,
                                budget_reservation.c.correlation_id == correlation_id,
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise UnknownReservationError(
                        f"correlation_id={correlation_id!r} was never reserved for org "
                        f"{organization_id}"
                    )
                if row["status"] in _TERMINAL_STATUSES:
                    await uow.commit()
                    return  # idempotent no-op

                await session.execute(
                    update(org_budget)
                    .where(org_budget.c.organization_id == organization_id)
                    .values(reserved=org_budget.c.reserved - row["estimated_cost"])
                )
                await session.execute(
                    update(budget_reservation)
                    .where(budget_reservation.c.id == row["id"])
                    .values(status="released", settled_at=func.now())
                )
                await uow.commit()
        except (LedgerUnavailableError, UnknownReservationError):
            raise
        except (SQLAlchemyError, OSError) as exc:
            # OSError covers a raw connection refusal (e.g. ConnectionRefusedError) that can
            # surface unwrapped, before SQLAlchemy's own exception translation applies - a
            # database that refuses the TCP connection outright is exactly as unavailable as
            # one that accepts the connection and then errors (ADR-0009 row 1: either way,
            # fail closed, never propagate a raw infrastructure exception to the caller).
            raise LedgerUnavailableError(str(exc)) from exc
