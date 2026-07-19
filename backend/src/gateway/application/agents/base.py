"""Shared agent scaffolding.

Every agent writes its typed result into the shared ``AgentContext`` and returns a
``ReasoningStep`` explaining itself. That split is deliberate: ``BaseAgent.contribute`` returning
a step is what makes participation-without-explanation impossible (invariant 3), while the typed
results the runtime needs to assemble a ``RoutingDecision`` travel in the context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from gateway.domain.routing.models import (
    CostDecision,
    HealthDecision,
    PlannerDecision,
    PolicyDecision,
)


@dataclass
class AgentContext:
    """Mutable working state passed down the agent chain.

    Mutable by design - it is the runtime's scratch space, not a domain object. The immutable
    artefact is the ``RoutingDecision`` the runtime builds from it.
    """

    organization_id: UUID
    correlation_id: str
    request: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[str, ...] = ()
    planner: PlannerDecision | None = None
    policy: PolicyDecision | None = None
    cost: CostDecision | None = None
    health: HealthDecision | None = None
    selected_provider: str | None = None
    selected_model: str | None = None
    confidence: float | None = None
