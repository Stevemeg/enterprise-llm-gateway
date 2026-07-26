"""Budget ledger seam (ADR-0016 Slice 9, ADR-0017) - a **capability-owned** port, not Tier-1.

**The only budget authority in the system.** ``reserve`` must succeed before ``ProviderExecutor``
is invoked, and a rejected reservation means the provider is never called. Every operation is
atomic and durable against real PostgreSQL (ADR-0017). ``correlation_id`` (from
``InferenceRequest``, Slice 7) is the identity every operation keys on, scoped per-organization:
it is a caller-supplied string with no reason to be globally unique across tenants.

## Phase 5 M2: it is now the *sole* budget seam

Slice 8 introduced a second one - ``BudgetPort``/``BudgetEnforcer``/``InMemoryBudgetStore`` -
which classified spend *after* the provider had already responded. This port superseded that
purpose in Slice 9, and Phase 4 closed with the older layer constructed in the composition root
and called by nothing: no production path, no consumer, and no reader for its output. Under GP-1
("architecture evolves only through evidence", clause 1: a completed milestone exposes a
limitation), a seam that a whole phase failed to acquire a consumer for is not deferred work; it
is over-built architecture, and it was removed in M2 rather than kept for its history. Two budget
seams also meant two answers to "can this tenant afford it", which is precisely the second source
of truth Rule 3 exists to prevent.

``UnsupportedCurrencyError`` moved here from that deleted module, because the ledger is now its
only raiser. Its meaning is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from gateway.application.ports.money import Money


class ReservationOutcome(StrEnum):
    """Closed vocabulary for how a reservation attempt ended (safe as a metric label).

    A ``BudgetLedgerPort`` implementation's own ``reserve`` only ever produces ``RESERVED`` or
    ``EXCEEDED`` - a store outage is a raised ``LedgerUnavailableError``, never a fabricated
    outcome. ``UNAVAILABLE`` exists so ``ReservationService`` (the orchestrator above this port,
    which catches that error) has one result type to return uniformly, whether the ledger
    answered or could not be reached.
    """

    RESERVED = "reserved"
    EXCEEDED = "exceeded"
    UNAVAILABLE = "unavailable"


class LedgerUnavailableError(RuntimeError):
    """The ledger store could not be reached.

    Never a business outcome - callers fail closed on this (ADR-0009 row 1: a hard budget store
    outage must reject, never silently allow unbounded spend).
    """


class UnsupportedCurrencyError(RuntimeError):
    """A cost was computed in a currency the org's budget is not denominated in.

    A configuration defect - this project performs no currency conversion - never a budget denial,
    the same distinction ``UnknownPriceError`` draws for a missing price.
    """


class UnknownReservationError(RuntimeError):
    """``settle``/``release`` was called for a ``correlation_id`` that was never reserved.

    A caller defect (settling something never reserved), never a business outcome - mirrors how
    ``CostAccountant`` treats a missing/malformed precondition as an exception, not a decision.
    """


@dataclass(frozen=True, slots=True)
class SettlementDetail:
    """Everything ``settle`` needs to both release a reservation's hold and write a durable
    actual-cost record, in the same atomic operation (Rule 3: the budget total and the ledger
    entry must agree on one committed value - two independently-committing writes could leave a
    reservation released with no matching ledger row, or vice versa, on a crash between them).

    Deliberately not the accounting layer's ``CostRecord``: this port must not import a concrete
    orchestrator's type (``application/accounting/cost_accountant.py`` is not a port). Carries the
    same facts a ``CostRecord`` does, restated as a port-local shape.
    """

    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    input_cost: Money
    output_cost: Money
    total_cost: Money


@dataclass(frozen=True, slots=True)
class ReservationResult:
    """The result of one ``reserve`` call. Immutable, like ``BudgetDecision``."""

    outcome: ReservationOutcome
    organization_id: UUID
    correlation_id: str
    estimated_cost: Money
    remaining: Money | None = None

    @property
    def permitted(self) -> bool:
        return self.outcome is ReservationOutcome.RESERVED


@runtime_checkable
class BudgetLedgerPort(Protocol):
    """Atomic reserve/commit/release against a durable, tenant-scoped budget ledger."""

    async def reserve(
        self, organization_id: UUID, correlation_id: str, estimated_cost: Money
    ) -> ReservationResult:
        """Atomically check-and-hold ``estimated_cost`` against the org's budget.

        Idempotent: a repeated call with the same ``(organization_id, correlation_id)`` returns
        the outcome originally decided, without re-reserving. A rejected (``EXCEEDED``) attempt
        holds nothing, so a later attempt with the same id may re-evaluate current budget state -
        unlike a successful reservation, there is no monetary effect to double.

        Raises ``LedgerUnavailableError`` if the store cannot be reached - never a fabricated
        decision.
        """
        ...

    async def settle(
        self, organization_id: UUID, correlation_id: str, detail: SettlementDetail
    ) -> None:
        """Release the reservation's hold, record ``detail.total_cost`` as spent, and write a
        durable actual-cost record - atomically, in one transaction.

        Idempotent: settling an already-committed ``correlation_id`` again is a no-op (never
        double-books spend). Raises ``UnknownReservationError`` if ``correlation_id`` was never
        reserved. Raises ``LedgerUnavailableError`` if the store cannot be reached.

        **A late settlement against an ``expired`` reservation still books the spend** (Phase 5
        M2). The tokens were genuinely consumed, so refusing would under-bill; but the hold was
        already handed back by reconciliation, so the implementation must record the spend
        *without* returning the hold a second time. Returning it twice would drive
        ``org_budget.reserved`` below what is actually held - and, at the boundary, below zero.
        """
        ...

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        """Release a reservation's hold without recording any spend (no usage was incurred).

        Idempotent: releasing an already-released, already-committed or already-expired
        reservation is a no-op. Raises ``UnknownReservationError`` if ``correlation_id`` was never
        reserved.
        """
        ...

    async def reconcile_expired(self, organization_id: UUID, *, older_than: datetime) -> int:
        """Reclaim this tenant's holds created before ``older_than`` that are still ``reserved``,
        returning how many were reclaimed. Atomic per reclaimed hold; safe to run concurrently.

        **Rule 5 event (Phase 5 M2).** *Active consumer:*
        ``application/accounting/reservation_reconciler.py`` - the first thing that must reclaim a
        hold whose owner is gone. *Why the protocol was insufficient:* ``release`` needs a
        ``correlation_id``, and the whole problem is that nobody knows the ids of the requests a
        crashed process was serving. There was no operation that could ask "what is stale". *Why
        it does not belong in the consumer:* returning a hold means decrementing
        ``org_budget.reserved`` and marking the reservation in one indivisible step, against
        concurrent settlement of the very same row. That atomicity is this port's entire reason
        for existing (ADR-0017) and cannot be assembled from ``reserve``/``settle``/``release``.

        **Tenant-scoped, never global.** An implementation reclaims one organization's holds and
        must not need to see another's - which is what keeps it compatible with FORCE row-level
        security instead of requiring a privileged cross-tenant sweep (ADR-0014, and ADR-0019's
        standing rule that any further ``SECURITY DEFINER`` needs its own ADR).

        Idempotent: a second call reclaims nothing, because the first left no hold in ``reserved``.
        Two concurrent reconcilers must not both reclaim the same hold, and a reconciler racing a
        ``settle`` for the same reservation must not let the pair double-count.

        Raises ``LedgerUnavailableError`` if the store cannot be reached.
        """
        ...
