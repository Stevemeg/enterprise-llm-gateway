"""Routing engine seam (ADR-0016 Slice 6) - a **capability-owned** port, not a Tier-1 protocol.

Tier 1 was untouched by this milestone (Rule 5 not triggered). This port exists so the pipeline
adapter depends on an abstraction rather than on a concrete orchestrator, which is what keeps
``AgentRoutingStage`` a transport.

## Why there is no null implementation

Rule 4 asks for a trivial implementation to validate a port. **This port cannot have one**, and
that is a result rather than an omission: any engine must return a ``RoutingExecution``, which
carries a ``RoutingDecision``, and only ``AgentRuntime`` may construct one (invariant 3). A null
engine would have to fabricate a decision - an unexplained routing outcome, exactly what the
invariant forbids. The explainability invariant therefore *excludes* a null implementation here.
The port is instead validated by the real engine plus a stub ``ProviderCatalog``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from gateway.application.routing.catalog import ProviderDescriptor
from gateway.domain.routing.models import RoutingDecision, RoutingOutcome


class RoutingIntegrityError(RuntimeError):
    """The runtime selected a provider the catalog cannot resolve.

    Not a routing outcome - a routing outcome is something the agents decided and explained. This
    means the engine supplied candidates that disagree with its own catalog, which is a defect in
    the engine, not a fact about the request. Raising keeps it out of the decision record, where
    it would masquerade as an explained denial.
    """


@dataclass(frozen=True, slots=True)
class RoutingExecution:
    """The engine's output: an unmodified decision plus the provider it resolves to.

    ``decision`` is the **only** explanation. This wrapper deliberately carries no reason, no
    message and no status of its own - if it did, there would be two accounts of why a request
    routed the way it did, and they would eventually disagree.
    """

    decision: RoutingDecision
    provider: ProviderDescriptor | None = None

    @property
    def routed(self) -> bool:
        return self.decision.outcome is RoutingOutcome.SELECTED and self.provider is not None


@runtime_checkable
class RoutingEngine(Protocol):
    """Orchestrates a routing attempt end to end."""

    async def route(
        self,
        *,
        organization_id: UUID,
        correlation_id: str,
        request: dict[str, Any] | None = None,
    ) -> RoutingExecution:
        """Resolve candidates, obtain a decision, and resolve the selection. Never invents one."""
        ...
