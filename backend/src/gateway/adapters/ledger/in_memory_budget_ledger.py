"""Single-process, in-memory BudgetLedgerPort (ADR-0016 Slice 9, Rule 4).

## Documented limitations (not omissions)

- **Not atomic.** A single Python ``dict`` mutation under ``asyncio`` has no concurrent writers
  within one process (there is no `await` between check and write), so this happens to be
  race-free *for a single process* - but that is an accident of the event loop, not a proven
  guarantee, and it is certainly not atomic across replicas. It does not exercise the same
  property ``SqlBudgetLedger`` proves against real PostgreSQL (row-level locking under genuine
  concurrent connections). Existing only so unit tests can exercise ``ReservationService`` without
  a database, and so the port has a second, mutually-independent implementation (Rule 4).
- **Not durable.** State is a process-local dict; a restart forgets every reservation and budget.
- **Not distributed.** Multiple gateway replicas would each keep independent totals.

Concurrency and RLS claims are proven only by ``SqlBudgetLedger`` against real PostgreSQL
(``tests/integration/test_budget_ledger_postgres.py``) - never by this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from gateway.application.ports.ledger import (
    BudgetLedgerPort,
    LedgerUnavailableError,
    ReservationOutcome,
    ReservationResult,
    SettlementDetail,
    UnknownReservationError,
)
from gateway.application.ports.money import Money
from gateway.shared.clock import Clock, SystemClock

_RESERVED = "reserved"
_COMMITTED = "committed"
_RELEASED = "released"
_EXPIRED = "expired"
#: Statuses whose hold has already left ``reserved``. Mirrors ``SqlBudgetLedger`` exactly: the two
#: implementations must agree on when a hold has already been handed back, or the Rule-4 parity
#: they exist to demonstrate would be comparing two different contracts.
_HOLD_ALREADY_RETURNED = (_COMMITTED, _RELEASED, _EXPIRED)


@dataclass
class _Reservation:
    correlation_id: str
    estimated_cost: Money
    status: str  # "reserved" | "committed" | "released" | "expired"
    #: When the hold was taken. Phase 5 M2 added it for one reason: reconciliation asks "what is
    #: stale", and staleness is age. Nothing else reads it.
    created_at: datetime


@dataclass
class _OrgLedger:
    limit: Money | None = None
    reserved: Decimal = Decimal(0)
    spent: Decimal = Decimal(0)
    reservations: dict[str, _Reservation] = field(default_factory=dict)


class InMemoryBudgetLedger(BudgetLedgerPort):
    """Org-scoped reserve/commit/release, held entirely in process memory."""

    def __init__(
        self,
        limits: dict[UUID, Money] | None = None,
        *,
        unavailable: bool = False,
        clock: Clock | None = None,
    ) -> None:
        self._orgs: dict[UUID, _OrgLedger] = {
            org: _OrgLedger(limit=limit) for org, limit in (limits or {}).items()
        }
        # A construction-time toggle to simulate a store outage in tests.
        self._unavailable = unavailable
        # Injectable so a test can age a hold without sleeping, exactly as every other
        # time-dependent component in this project takes a Clock.
        self._clock: Clock = clock or SystemClock()

    def _ledger_for(self, organization_id: UUID) -> _OrgLedger:
        return self._orgs.setdefault(organization_id, _OrgLedger())

    async def reserve(
        self, organization_id: UUID, correlation_id: str, estimated_cost: Money
    ) -> ReservationResult:
        if self._unavailable:
            raise LedgerUnavailableError("simulated ledger store outage")
        ledger = self._ledger_for(organization_id)

        existing = ledger.reservations.get(correlation_id)
        if existing is not None and existing.status not in (_RELEASED, _EXPIRED):
            # Idempotent replay: the original decision stands, never re-evaluated. Only a *live*
            # ("reserved") or already-settled ("committed") reservation replays - a released or
            # EXPIRED one is deliberately excluded and re-held below, because its hold was already
            # given back (replaying it would report RESERVED while holding nothing). Mirrors
            # SqlBudgetLedger, including the Phase 5 M2 addition of "expired" to that exclusion.
            return ReservationResult(
                outcome=ReservationOutcome.RESERVED,
                organization_id=organization_id,
                correlation_id=correlation_id,
                estimated_cost=existing.estimated_cost,
            )

        if ledger.limit is None:
            ledger.reservations[correlation_id] = _Reservation(
                correlation_id, estimated_cost, _RESERVED, self._clock.now()
            )
            return ReservationResult(
                outcome=ReservationOutcome.RESERVED,
                organization_id=organization_id,
                correlation_id=correlation_id,
                estimated_cost=estimated_cost,
            )

        remaining_amount = ledger.limit.amount - ledger.spent - ledger.reserved
        if estimated_cost.amount > remaining_amount:
            return ReservationResult(
                outcome=ReservationOutcome.EXCEEDED,
                organization_id=organization_id,
                correlation_id=correlation_id,
                estimated_cost=estimated_cost,
                remaining=Money(remaining_amount, ledger.limit.currency),
            )

        ledger.reserved += estimated_cost.amount
        ledger.reservations[correlation_id] = _Reservation(
            correlation_id, estimated_cost, _RESERVED, self._clock.now()
        )
        return ReservationResult(
            outcome=ReservationOutcome.RESERVED,
            organization_id=organization_id,
            correlation_id=correlation_id,
            estimated_cost=estimated_cost,
        )

    async def settle(
        self, organization_id: UUID, correlation_id: str, detail: SettlementDetail
    ) -> None:
        if self._unavailable:
            raise LedgerUnavailableError("simulated ledger store outage")
        ledger = self._ledger_for(organization_id)
        reservation = ledger.reservations.get(correlation_id)
        if reservation is None:
            raise UnknownReservationError(
                f"correlation_id={correlation_id!r} was never reserved for org {organization_id}"
            )
        if reservation.status == _COMMITTED:
            return  # idempotent replay - already settled, never double-book
        # A late settlement against an EXPIRED hold books the spend but must not return the hold
        # a second time - reconciliation already did (Phase 5 M2, mirroring SqlBudgetLedger).
        if reservation.status == _RESERVED:
            ledger.reserved -= reservation.estimated_cost.amount
        ledger.spent += detail.total_cost.amount
        reservation.status = _COMMITTED

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        if self._unavailable:
            raise LedgerUnavailableError("simulated ledger store outage")
        ledger = self._ledger_for(organization_id)
        reservation = ledger.reservations.get(correlation_id)
        if reservation is None:
            raise UnknownReservationError(
                f"correlation_id={correlation_id!r} was never reserved for org {organization_id}"
            )
        if reservation.status in _HOLD_ALREADY_RETURNED:
            return  # idempotent no-op - including for a hold reconciliation reclaimed
        ledger.reserved -= reservation.estimated_cost.amount
        reservation.status = _RELEASED

    async def reconcile_expired(self, organization_id: UUID, *, older_than: datetime) -> int:
        """Reclaim this org's holds taken before ``older_than`` that are still ``reserved``.

        Single-process and non-atomic, exactly like every other method here: it demonstrates the
        *contract* (idempotent, tenant-scoped, hold returned exactly once) so unit tests can
        exercise ``ReservationReconciler`` without a database. It proves nothing about two
        reconcilers racing - only ``SqlBudgetLedger`` against real PostgreSQL does that.
        """
        if self._unavailable:
            raise LedgerUnavailableError("simulated ledger store outage")
        ledger = self._ledger_for(organization_id)
        stale = [
            reservation
            for reservation in ledger.reservations.values()
            if reservation.status == _RESERVED and reservation.created_at < older_than
        ]
        for reservation in stale:
            ledger.reserved -= reservation.estimated_cost.amount
            reservation.status = _EXPIRED
        return len(stale)
