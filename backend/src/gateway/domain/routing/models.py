"""Routing domain objects (ADR-0016, Tier-1 invariant 3).

``RoutingDecision`` is the structural form of the invariant "routing decisions must be
explainable". Explainability as a *semantic* rule is unenforceable - a reviewer can only read
code and hope. Returning a typed record instead of a bare provider makes it structural: a
decision **cannot** be produced without its reasoning trace, because the return type demands one.

Nothing downstream consumes a bare provider choice. Metrics, audit and debugging all derive from
this record rather than from ad-hoc logging, so the reasoning cannot drift out of sync with the
decision that was actually taken.

These are plain frozen dataclasses - no framework types, no I/O (Clean Architecture, ADR-0001).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class RoutingOutcome(StrEnum):
    """Closed vocabulary for how a routing attempt ended (safe as a metric label)."""

    SELECTED = "selected"
    NO_CANDIDATE = "no_candidate"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    BUDGET_EXCEEDED = "budget_exceeded"
    ALL_UNHEALTHY = "all_unhealthy"


@dataclass(frozen=True, slots=True)
class ReasoningStep:
    """One agent's contribution to a decision.

    ``agent`` identifies who spoke, ``summary`` is human-readable, ``detail`` is structured for
    machines. Keeping both means an operator can read the trace and a dashboard can aggregate it
    without re-parsing prose.
    """

    agent: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlannerDecision:
    """What the request appears to need (intent, complexity, constraints)."""

    intent: str
    complexity: str
    required_capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Whether the request is permitted, and what it is confined to."""

    allowed: bool
    reason: str | None = None
    allowed_providers: tuple[str, ...] = ()
    allowed_regions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CostDecision:
    """Estimated cost and the budget headroom that remains."""

    estimated_cost: float
    currency: str = "USD"
    within_budget: bool = True
    budget_remaining: float | None = None


@dataclass(frozen=True, slots=True)
class HealthDecision:
    """Which candidates are currently usable."""

    healthy_candidates: tuple[str, ...] = ()
    degraded_candidates: tuple[str, ...] = ()
    excluded_candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The complete, explainable result of routing one request.

    ``reasoning_steps`` must be non-empty for any decision (CI-enforced): a decision with no
    recorded reasoning is indistinguishable from one that was never explained.
    """

    outcome: RoutingOutcome
    organization_id: UUID
    correlation_id: str
    decided_at: datetime
    reasoning_steps: tuple[ReasoningStep, ...]
    selected_provider: str | None = None
    selected_model: str | None = None
    planner_result: PlannerDecision | None = None
    policy_result: PolicyDecision | None = None
    cost_result: CostDecision | None = None
    health_result: HealthDecision | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_selection(self) -> bool:
        return self.outcome is RoutingOutcome.SELECTED and self.selected_provider is not None

    def agents_consulted(self) -> tuple[str, ...]:
        """Distinct agents that contributed - the basis of the CI completeness check."""
        seen: dict[str, None] = {}
        for step in self.reasoning_steps:
            seen.setdefault(step.agent, None)
        return tuple(seen)
