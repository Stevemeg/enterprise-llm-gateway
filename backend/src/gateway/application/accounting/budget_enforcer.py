"""BudgetEnforcer - decides whether a cost fits an organization's budget (ADR-0016 Slice 8).

One job: ``CostRecord's Money x BudgetSnapshot -> BudgetDecision``. It does not compute cost
(``CostAccountant``'s job), does not call a provider, does not reroute, does not authorize a
principal (RBAC's job, a different concern entirely) and never touches ``RoutingDecision``.

## What "enforcement" honestly means here

This evaluates spend that has **already happened** - it runs after ``CostAccountant``, which runs
after ``ProviderExecutor``, which runs after the provider already responded. There is no call left
to block. "Enforcement" here means: classify the just-incurred cost against the budget
(``ALLOWED``/``EXCEEDED``/``UNAVAILABLE``) so it can be recorded, alerted on, and read by a future
routing attempt's ``CostAgent`` (unchanged by this slice) - not that this request's own provider
call was ever gate-able. Pre-call affordability estimation is ``CostAgent``'s existing job and is
untouched here.

``evaluate`` and ``BudgetPort.record`` are two separate calls, not one atomic operation - read
the module docstring in ``application/ports/budget.py`` for why that is a documented limitation
rather than an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from gateway.application.ports.budget import (
    BudgetPort,
    BudgetUnavailableError,
    UnsupportedCurrencyError,
)
from gateway.application.ports.money import Money


class BudgetOutcome(StrEnum):
    """Closed vocabulary for how a budget evaluation ended (safe as a metric label)."""

    ALLOWED = "allowed"
    EXCEEDED = "exceeded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    """The result of evaluating one cost against one organization's budget."""

    outcome: BudgetOutcome
    organization_id: UUID
    cost: Money
    remaining: Money | None = None
    limit: Money | None = None

    @property
    def permitted(self) -> bool:
        return self.outcome is BudgetOutcome.ALLOWED


class BudgetEnforcer:
    """Classifies a cost against an organization's hard budget."""

    def __init__(self, budget: BudgetPort) -> None:
        self._budget = budget

    async def evaluate(self, organization_id: UUID, cost: Money) -> BudgetDecision:
        """Classify ``cost`` against the org's current budget. Never raises for a budget-store
        outage - fails closed (ADR-0009 row 1: a hard budget store outage must reject, never
        silently allow unbounded spend)."""
        try:
            snapshot = await self._budget.snapshot(organization_id)
        except BudgetUnavailableError:
            return BudgetDecision(
                outcome=BudgetOutcome.UNAVAILABLE, organization_id=organization_id, cost=cost
            )

        if snapshot is None:
            # No budget configured for this org is an ordinary, allowed outcome (unbounded) -
            # distinct from the store being unreachable, which fails closed above.
            return BudgetDecision(
                outcome=BudgetOutcome.ALLOWED, organization_id=organization_id, cost=cost
            )

        remaining = snapshot.remaining
        if cost.currency != remaining.currency:
            raise UnsupportedCurrencyError(
                f"cost currency {cost.currency!r} does not match budget currency "
                f"{remaining.currency!r} for organization {organization_id}"
            )

        outcome = (
            BudgetOutcome.ALLOWED if cost.amount <= remaining.amount else BudgetOutcome.EXCEEDED
        )
        return BudgetDecision(
            outcome=outcome,
            organization_id=organization_id,
            cost=cost,
            remaining=remaining,
            limit=snapshot.limit,
        )
