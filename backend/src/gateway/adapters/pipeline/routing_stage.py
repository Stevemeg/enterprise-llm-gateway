"""AgentRuntime as a pipeline stage (ADR-0016 invariants 3 and 5).

This is the first real consumer of the ``PipelineStage`` seam. It adds **no** routing logic and
**no** new pipeline behaviour: it runs the agent chain and translates the resulting
``RoutingDecision`` into stage terms.

**This stage transports; it never adjudicates.** It always returns ANNOTATE, carrying the
``RoutingDecision`` for later stages, whatever the outcome was. Blocking on a non-selection would
put policy in the pipeline stage when the runtime has already decided, and would have to be
revisited once Policy, Evaluation and Reflection become stages in their own right.

Responsibilities stay separated (Slice 6 moved orchestration out of this adapter):
  * ``AgentRuntime``   - sequences agents and produces the decision
  * ``RoutingEngine``  - orchestrates: supplies candidates, resolves the selection
  * ``AgentRoutingStage`` - transports the result
  * ``RequestPipeline``   - controls execution (Slice 14)
  * later stages       - consume the decision and decide what to do about it

## Slice 15: it transports the whole ``RoutingExecution``, not just the decision

The first end-to-end composition exposed a defect here. This stage published only
``execution.decision``, which looked right - the decision is the sole explanation, and the stage's
own contract is to transport an explanation rather than adjudicate. But ``RoutingExecution.routed``
means "SELECTED **and** a provider was resolved", so the annotation could report that a provider
had been chosen while carrying nothing capable of calling it. Nothing noticed for nine slices
because nothing ever executed the pipeline.

Transporting the whole object is the smaller correction: it is still one annotation, still one
source of truth, and ``decision`` remains reachable as ``execution.decision``. The alternative -
a second key alongside the first - would have put two views of one result into the bag, which is
the shape this stage's own docstring warns against.
"""

from __future__ import annotations

from typing import Any

from gateway.application.ports.pipeline import StageAction, StageContext, StageResult
from gateway.application.ports.routing import ROUTING_EXECUTION_KEY, RoutingEngine


class AgentRoutingStage:
    """Runs the agent chain and publishes its decision to the pipeline."""

    def __init__(self, engine: RoutingEngine, *, name: str = "agent_routing") -> None:
        self._engine = engine
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def before_request(self, context: StageContext) -> StageResult:
        if context.organization_id is None:
            # Routing is tenant-scoped; with no tenant there is no decision to transport.
            # Not a block - deciding what a missing decision means belongs to later stages.
            return StageResult()

        # Candidates are the engine's business now: it owns the catalog. A stage that also
        # supplied them would be making a routing input decision while claiming to transport.
        request: dict[str, Any] = dict(context.attributes.get("request", {}))
        execution = await self._engine.route(
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            request=request,
        )
        # Always ANNOTATE: every outcome - selection, denial, no candidate - is transported
        # identically, so downstream consumers need no special case for a rejected decision.
        return StageResult(
            action=StageAction.ANNOTATE, annotations={ROUTING_EXECUTION_KEY: execution}
        )
