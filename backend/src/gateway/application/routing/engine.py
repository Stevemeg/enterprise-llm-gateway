"""AgentOrchestratedRoutingEngine - the first production routing orchestrator (ADR-0016 Slice 6).

Three orchestration layers, each with one job:

* ``AgentRuntime``   - sequences agents and *decides*, producing the sole explanation.
* ``RoutingEngine``  - supplies candidates, invokes the runtime, resolves the selection.
* ``AgentRoutingStage`` - transports the result through the pipeline.

The engine adds **no** routing intelligence. It never re-ranks candidates, never overrides an
outcome, never retries and never second-guesses policy, cost or health: those verdicts arrive
already made and already explained, and the engine's only correct response is to respect them.
Anything more would make it a second router competing with the agents.

It also never constructs a ``RoutingDecision`` (invariant 3, CI-enforced). When the runtime
declines to select, the engine returns that decision unchanged with no provider attached - the
denial explains itself.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from gateway.application.agents.runtime import AgentRuntime
from gateway.application.ports.routing import (
    RoutingExecution,
    RoutingIntegrityError,
)
from gateway.application.routing.catalog import ProviderCatalog
from gateway.domain.routing.models import RoutingOutcome
from gateway.observability.metrics import record_routing_decision


class AgentOrchestratedRoutingEngine:
    """Routes by orchestrating the agent runtime over a provider catalog."""

    def __init__(self, catalog: ProviderCatalog, runtime: AgentRuntime) -> None:
        self._catalog = catalog
        self._runtime = runtime

    async def route(
        self,
        *,
        organization_id: UUID,
        correlation_id: str,
        request: dict[str, Any] | None = None,
    ) -> RoutingExecution:
        candidates = await self._catalog.candidates(organization_id)
        # An empty catalog is not an error. It flows into the runtime as no candidates, and the
        # runtime returns NO_CANDIDATE with a full reasoning trace - a denial that explains
        # itself, rather than an exception the caller has to interpret.
        decision = await self._runtime.decide(
            organization_id=organization_id,
            correlation_id=correlation_id,
            request=request,
            candidates=tuple(descriptor.name for descriptor in candidates),
        )
        # Slice 16: the engine owns the routing attempt end to end, so it reports the outcome.
        # Read off the decision the runtime already made - RoutingDecision is Tier-1 and gained
        # no field for this.
        record_routing_decision(outcome=decision.outcome.value)

        if decision.outcome is not RoutingOutcome.SELECTED:
            return RoutingExecution(decision=decision)

        provider = await self._catalog.get(organization_id, decision.selected_provider or "")
        if provider is None:
            # The runtime can only select from candidates this engine supplied, so this is
            # unreachable unless the catalog changed mid-flight or the two disagree. Raising
            # keeps a defect out of the decision record instead of dressing it as a denial.
            raise RoutingIntegrityError(
                f"runtime selected {decision.selected_provider!r}, absent from the catalog"
            )
        return RoutingExecution(decision=decision, provider=provider)
