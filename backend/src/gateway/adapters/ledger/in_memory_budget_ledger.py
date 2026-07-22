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


@dataclass
class _Reservation:
    correlation_id: str
    estimated_cost: Money
    status: str  # "reserved" | "committed" | "released"


@dataclass
class _OrgLedger:
    limit: Money | None = None
    reserved: Decimal = Decimal(0)
    spent: Decimal = Decimal(0)
    reservations: dict[str, _Reservation] = field(default_factory=dict)


class InMemoryBudgetLedger(BudgetLedgerPort):
    """Org-scoped reserve/commit/release, held entirely in process memory."""

    def __init__(
        self, limits: dict[UUID, Money] | None = None, *, unavailable: bool = False
    ) -> None:
        self._orgs: dict[UUID, _OrgLedger] = {
            org: _OrgLedger(limit=limit) for org, limit in (limits or {}).items()
        }
        # A construction-time toggle to simulate a store outage in tests.
        self._unavailable = unavailable

    def _ledger_for(self, organization_id: UUID) -> _OrgLedger:
        return self._orgs.setdefault(organization_id, _OrgLedger())

    async def reserve(
        self, organization_id: UUID, correlation_id: str, estimated_cost: Money
    ) -> ReservationResult:
        if self._unavailable:
            raise LedgerUnavailableError("simulated ledger store outage")
        ledger = self._ledger_for(organization_id)

        existing = ledger.reservations.get(correlation_id)
        if existing is not None:
            # Idempotent replay: the original decision stands, never re-evaluated.
            return ReservationResult(
                outcome=ReservationOutcome.RESERVED,
                organization_id=organization_id,
                correlation_id=correlation_id,
                estimated_cost=existing.estimated_cost,
            )

        if ledger.limit is None:
            ledger.reservations[correlation_id] = _Reservation(
                correlation_id, estimated_cost, "reserved"
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
            correlation_id, estimated_cost, "reserved"
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
        if reservation.status == "committed":
            return  # idempotent replay - already settled, never double-book
        ledger.reserved -= reservation.estimated_cost.amount
        ledger.spent += detail.total_cost.amount
        reservation.status = "committed"

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        if self._unavailable:
            raise LedgerUnavailableError("simulated ledger store outage")
        ledger = self._ledger_for(organization_id)
        reservation = ledger.reservations.get(correlation_id)
        if reservation is None:
            raise UnknownReservationError(
                f"correlation_id={correlation_id!r} was never reserved for org {organization_id}"
            )
        if reservation.status in ("committed", "released"):
            return  # idempotent no-op
        ledger.reserved -= reservation.estimated_cost.amount
        reservation.status = "released"
