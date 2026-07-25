"""AgentRuntime - sequences agents and builds the RoutingDecision (ADR-0016 invariant 3).

**This is the only place a ``RoutingDecision`` is constructed.** Centralising it is what makes
the explainability invariant structural rather than aspirational: no caller can obtain a routing
outcome without the reasoning trace, because no caller builds the record itself.

Ordering is fixed - planner, policy, cost, health, provider - and the runtime short-circuits as
soon as an outcome is determined (policy denial, budget exceeded, nothing healthy). A
short-circuit still returns a full ``RoutingDecision`` carrying every step taken so far: a
rejection must be as explainable as a selection, which is precisely where systems usually go
dark.

No provider calls, no MCP, no routing intelligence.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from gateway.application.agents.base import AgentContext
from gateway.application.ports.agents import BaseAgent
from gateway.domain.routing.models import (
    ReasoningStep,
    RoutingDecision,
    RoutingOutcome,
)
from gateway.shared.clock import Clock


class AgentRuntime:
    """Runs an ordered chain of agents and assembles their explainable decision."""

    def __init__(self, agents: Sequence[BaseAgent], clock: Clock) -> None:
        if not agents:
            # An empty chain would yield a decision with no reasoning, which the invariant
            # forbids. Fail at construction rather than produce an unexplainable outcome.
            raise ValueError("AgentRuntime requires at least one agent")
        self._agents = tuple(agents)
        self._clock = clock
        self._prepared = False

    @property
    def agents(self) -> tuple[BaseAgent, ...]:
        return self._agents

    async def prepare(self) -> None:
        """Prepare every agent once. Idempotent."""
        if self._prepared:
            return
        for agent in self._agents:
            await agent.prepare()
        self._prepared = True

    async def dispose(self) -> None:
        """Dispose every agent, even if one fails - a leaked resource must not mask the rest."""
        for agent in self._agents:
            await agent.dispose()
        self._prepared = False

    async def decide(
        self,
        *,
        organization_id: UUID,
        correlation_id: str,
        request: dict[str, Any] | None = None,
        candidates: Sequence[str] = (),
    ) -> RoutingDecision:
        """Run the chain and return an explainable decision. Never raises for a routing outcome."""
        await self.prepare()
        context = AgentContext(
            organization_id=organization_id,
            correlation_id=correlation_id,
            request=dict(request or {}),
            candidates=tuple(candidates),
        )
        shared: dict[str, Any] = {"agent_context": context}
        steps: list[ReasoningStep] = []

        for agent in self._agents:
            steps.append(await agent.contribute(shared))
            outcome = self._terminal_outcome(context)
            if outcome is not None:
                # Stop early, but return everything learned up to this point.
                return self._build(context, tuple(steps), outcome)

        outcome = (
            RoutingOutcome.SELECTED
            if context.selected_provider is not None
            else RoutingOutcome.NO_CANDIDATE
        )
        return self._build(context, tuple(steps), outcome)

    @staticmethod
    def _terminal_outcome(context: AgentContext) -> RoutingOutcome | None:
        """Whether the chain can stop early. Checked after every agent, not only at the end."""
        if context.policy is not None and not context.policy.allowed:
            return RoutingOutcome.BLOCKED_BY_POLICY
        if context.cost is not None and not context.cost.within_budget:
            return RoutingOutcome.BUDGET_EXCEEDED
        if (
            context.health is not None
            and not context.health.healthy_candidates
            and not context.health.degraded_candidates
            and context.candidates
        ):
            # ALL_UNHEALTHY only when nothing is usable. A degraded (half-open) candidate is
            # usable - it is a sanctioned recovery probe (Slice 20/21) - so a set that is all
            # degraded is routable, not all-unhealthy.
            return RoutingOutcome.ALL_UNHEALTHY
        return None

    def _build(
        self, context: AgentContext, steps: tuple[ReasoningStep, ...], outcome: RoutingOutcome
    ) -> RoutingDecision:
        selected = context.selected_provider if outcome is RoutingOutcome.SELECTED else None
        return RoutingDecision(
            outcome=outcome,
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            decided_at=self._clock.now(),
            reasoning_steps=steps,
            selected_provider=selected,
            selected_model=context.selected_model if selected else None,
            planner_result=context.planner,
            policy_result=context.policy,
            cost_result=context.cost,
            health_result=context.health,
            confidence=context.confidence if selected else None,
        )
