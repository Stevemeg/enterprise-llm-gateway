"""Budget seam (ADR-0016 Slice 8) - a **capability-owned** port, not a Tier-1 protocol.

Models every budget in this slice as **hard-enforced** only (FR-061). ``docs/Schema.sql``'s
`budget.limit_kind` documents a `soft` variant that warns rather than blocks (FR-067); nothing in
this slice consumes that branch, so no `limit_kind` field exists here (Rule 5) - adding one with
no reader would be exactly the speculative-field accumulation Rule 5 exists to prevent.

## What this port does not provide

This is **deterministic accounting**, not atomic concurrent enforcement. ``snapshot`` (read) and
``record`` (write) are two separate calls; nothing makes the read-decide-write sequence atomic
across concurrent requests. ADR-0004 rejected exactly this shape ("Option A - post-hoc accounting
only") as insufficient for *hard* concurrency-safe enforcement (FR-063, RISK-T03), in favor of an
atomic Redis Lua reserve/commit - which does not exist anywhere in this codebase yet. This port
does not fake that primitive. See ``application/accounting/budget_enforcer.py`` for the
consequence this has for what ``evaluate()`` can honestly claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from gateway.application.ports.money import Money


class BudgetUnavailableError(RuntimeError):
    """The budget store could not be reached.

    Never a business outcome - ``BudgetEnforcer`` fails closed on this (ADR-0009 row 1: a hard
    budget store outage must reject, never silently allow unbounded spend). Distinguished from an
    org simply having no budget configured, which ``snapshot`` reports as ``None`` and which *is*
    an ordinary, allowed outcome (unbounded).
    """


class UnsupportedCurrencyError(RuntimeError):
    """A cost was computed in a currency the org's budget is not denominated in.

    A configuration defect - this project performs no currency conversion - never a budget
    denial. Raised by the enforcer, not the port, because only the enforcer has both currencies
    to compare.
    """


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Point-in-time hard budget state for one organization."""

    organization_id: UUID
    limit: Money
    spent: Money

    def __post_init__(self) -> None:
        if self.spent.currency != self.limit.currency:
            raise UnsupportedCurrencyError(
                f"budget for {self.organization_id}: spent currency {self.spent.currency!r} "
                f"does not match limit currency {self.limit.currency!r}"
            )

    @property
    def remaining(self) -> Money:
        return Money(self.limit.amount - self.spent.amount, self.limit.currency)


@runtime_checkable
class BudgetPort(Protocol):
    """Reads and records organization-scoped hard-budget spend."""

    async def snapshot(self, organization_id: UUID) -> BudgetSnapshot | None:
        """Current budget state, or ``None`` if this org has no budget configured (unbounded).

        Raises ``BudgetUnavailableError`` if the store itself cannot be reached - never returns a
        fabricated snapshot to paper over an outage.
        """
        ...

    async def record(self, organization_id: UUID, cost: Money, *, idempotency_key: str) -> None:
        """Add ``cost`` to the org's spent total, unless ``idempotency_key`` was already applied.

        ``idempotency_key`` is the caller's stable identifier for the execution being accounted
        (this slice uses the request's ``correlation_id`` - see
        ``application/accounting/cost_accountant.py`` for why nothing new is minted here).
        Re-recording the same key is a no-op, preventing a retried accounting call from charging
        the same execution twice - but only within this process; nothing here durably survives a
        restart or coordinates across replicas.
        """
        ...
