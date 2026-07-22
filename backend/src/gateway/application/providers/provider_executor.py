"""ProviderExecutor - turns a routed selection into a provider call (ADR-0016 Slice 7).

Three orchestration layers now exist, each with one job (extending Slice 6's two):

* ``AgentRuntime``     - sequences agents and decides, producing the sole explanation.
* ``RoutingEngine``    - supplies candidates, invokes the runtime, resolves the selection.
* ``ProviderExecutor`` - turns a resolved selection into a provider call. Nothing more.

The executor adds **no** routing intelligence and makes **no** routing decision: it trusts
``RoutingExecution`` completely. It never re-selects a provider, never falls back to a different
one, and never inspects ``RoutingDecision`` beyond reading why routing declined - a second opinion
here would be a second router. It also never reaches ``AgentRuntime`` (Guard L, reused unchanged
from Slice 6: the routing engine remains the runtime's only caller).

Not a Rule-4 subject itself - the port under validation is ``ProviderClient``. This class is the
"real executor" the decision names: an orchestrator, not a protocol, so it has no null variant to
implement or ask for.
"""

from __future__ import annotations

from gateway.application.ports.providers import InferenceRequest, ProviderClient, ProviderResponse
from gateway.application.ports.routing import RoutingExecution


class ProviderExecutor:
    """Executes an inference request against the provider a routing attempt selected."""

    def __init__(self, client: ProviderClient) -> None:
        self._client = client

    async def execute(
        self, execution: RoutingExecution, request: InferenceRequest
    ) -> ProviderResponse:
        """Call the provider ``execution`` resolved to. Never overrides an unrouted decision."""
        provider = execution.provider
        if not execution.routed or provider is None:
            # Not an error - the decision already explains the refusal. Fabricating a provider
            # call for an unrouted request would be the executor overriding a decision it does
            # not own.
            return ProviderResponse(
                ok=False, error=f"not_routed: {execution.decision.outcome.value}"
            )
        return await self._client.invoke(provider, request)
