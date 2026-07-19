"""AgentRuntime as a pipeline stage (ADR-0016 invariants 3 and 5).

This is the first real consumer of the ``PipelineStage`` seam. It adds **no** routing logic and
**no** new pipeline behaviour: it runs the agent chain and translates the resulting
``RoutingDecision`` into stage terms.

**This stage transports; it never adjudicates.** It always returns ANNOTATE, carrying the
``RoutingDecision`` for later stages, whatever the outcome was. Blocking on a non-selection would
put policy in the pipeline stage when the runtime has already decided, and would have to be
revisited once Policy, Evaluation and Reflection become stages in their own right.

Responsibilities stay separated:
  * ``AgentRuntime``   - produces the decision
  * ``AgentRoutingStage`` - transports it
  * the pipeline executor - controls execution
  * later stages       - consume the decision and decide what to do about it
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.runtime import AgentRuntime
from gateway.application.ports.pipeline import StageAction, StageContext, StageResult

ROUTING_DECISION_KEY = "routing_decision"


class AgentRoutingStage:
    """Runs the agent chain and publishes its decision to the pipeline."""

    def __init__(self, runtime: AgentRuntime, *, name: str = "agent_routing") -> None:
        self._runtime = runtime
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def before_request(self, context: StageContext) -> StageResult:
        if context.organization_id is None:
            # Routing is tenant-scoped; with no tenant there is no decision to transport.
            # Not a block - deciding what a missing decision means belongs to later stages.
            return StageResult()

        request: dict[str, Any] = dict(context.attributes.get("request", {}))
        candidates = tuple(context.attributes.get("candidates", ()))

        decision = await self._runtime.decide(
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            request=request,
            candidates=candidates,
        )
        # Always ANNOTATE: every outcome - selection, denial, no candidate - is transported
        # identically, so downstream consumers need no special case for a rejected decision.
        return StageResult(
            action=StageAction.ANNOTATE, annotations={ROUTING_DECISION_KEY: decision}
        )

    async def after_response(self, context: StageContext) -> StageResult:
        return StageResult()

    async def on_error(self, context: StageContext, error: Exception) -> StageResult:
        return StageResult()
