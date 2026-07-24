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

## Rule 5 event (Slice 15): ``ROUTING_EXECUTION_KEY`` declared here

**Active consumer:** ``application/serving/inference_service.py`` (new in Slice 15) - the first
component that reads a routing result back out of an admitted request in order to execute it.

**Why the existing arrangement was insufficient:** the key naming routing's pipeline annotation was
a private constant inside ``adapters/pipeline/routing_stage.py``. An application-layer consumer
cannot import it (Clean Architecture forbids application -> adapters, CI-enforced), so before this
slice the only way to read the annotation was to re-declare the literal string at the consumer -
two spellings of one contract, drifting silently the first time either changed. That is precisely
the failure Rule 3 exists to prevent.

**Why the change does not belong in the consumer instead:** producer and consumer must agree, and
the agreement belongs beside the type being transported. This mirrors ``REQUEST_PAYLOAD_KEY`` in
``ports/policy.py`` and ``REQUIRED_PERMISSIONS_KEY`` in
``application/authorization/requirements.py`` - both live with the capability that owns the
concept, not with the adapter that emits it.

Capability-owned port, so this is a Rule 5 event recorded in the evidence log, not a new ADR.
Tier 1 is untouched: ``StageResult.annotations`` remains ``dict[str, Any]`` and no protocol changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from gateway.application.routing.catalog import ProviderDescriptor
from gateway.domain.routing.models import RoutingDecision, RoutingOutcome

#: Key under which ``AgentRoutingStage`` publishes its ``RoutingExecution`` to the pipeline.
#: The whole execution, never a projection of it - see ``RoutingExecution`` below.
ROUTING_EXECUTION_KEY = "routing_execution"


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

    **The whole object is what travels through the pipeline** (Slice 15). Until that slice
    ``AgentRoutingStage`` annotated only ``decision``, which read as sufficient - the decision is
    the explanation - but silently dropped ``provider``. Since ``routed`` is exactly
    "SELECTED *and* a provider was resolved", the transported half could say a provider had been
    chosen while carrying nothing able to execute it. That was invisible until something
    downstream tried; see the evidence log.
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
