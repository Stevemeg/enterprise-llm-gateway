"""Budget ledger seam (ADR-0016 Slice 9, ADR-0017) - a **capability-owned** port, not Tier-1.

Answers a different question than ``BudgetPort`` (Slice 8): ``BudgetPort``/``BudgetEnforcer``
classify spend that has *already happened*, after the provider already responded - a documented
limitation, not a defect (see ``application/ports/budget.py``). This port exists so a caller can
gate a provider call *before* it happens: ``reserve`` must succeed before ``ProviderExecutor`` is
invoked, and a rejected reservation means the provider is never called. Slice 8's ``BudgetPort``
is unchanged and still valid for its own purpose; nothing here replaces it.

``BudgetPort`` is not extended with reserve/commit methods instead of adding this port because its
own docstring already disclaims exactly this shape ("this port does not fake that primitive") -
bolting reservation onto a port that documents its own non-atomicity would contradict its own
contract. A new port keeps each seam's guarantee honest (Rule 3).

Every operation is atomic and durable against real PostgreSQL (ADR-0017) - not merely
"best-effort", the way ``InMemoryBudgetStore`` is for ``BudgetPort``. ``correlation_id`` (from
``InferenceRequest``, Slice 7) is the identity every operation keys on, scoped per-organization:
it is a caller-supplied string with no reason to be globally unique across tenants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from gateway.application.ports.money import Money


class ReservationOutcome(StrEnum):
    """Closed vocabulary for how a reservation attempt ended (safe as a metric label).

    A ``BudgetLedgerPort`` implementation's own ``reserve`` only ever produces ``RESERVED`` or
    ``EXCEEDED`` - a store outage is a raised ``LedgerUnavailableError``, never a fabricated
    outcome. ``UNAVAILABLE`` exists so ``ReservationService`` (the orchestrator above this port,
    mirroring how ``BudgetEnforcer`` catches ``BudgetUnavailableError``) has one result type to
    return uniformly, whether the ledger answered or could not be reached.
    """

    RESERVED = "reserved"
    EXCEEDED = "exceeded"
    UNAVAILABLE = "unavailable"


class LedgerUnavailableError(RuntimeError):
    """The ledger store could not be reached.

    Never a business outcome - callers fail closed on this (ADR-0009 row 1: a hard budget store
    outage must reject, never silently allow unbounded spend), mirroring ``BudgetUnavailableError``.
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
        """
        ...

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        """Release a reservation's hold without recording any spend (no usage was incurred).

        Idempotent: releasing an already-released or already-committed reservation is a no-op.
        Raises ``UnknownReservationError`` if ``correlation_id`` was never reserved.
        """
        ...
