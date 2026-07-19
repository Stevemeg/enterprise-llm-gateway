"""ProviderAgent (stub) - picks the first healthy candidate.

No provider SDK, no network call. Selection intelligence (cost/latency/quality weighting) is the
routing-engine milestone; this agent only proves that a selection flows into ``RoutingDecision``.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.domain.routing.models import ReasoningStep


class ProviderAgent:
    def __init__(self, name: str = "provider") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        healthy = agent_context.health.healthy_candidates if agent_context.health else ()
        if healthy:
            agent_context.selected_provider = healthy[0]
            agent_context.confidence = 1.0 / len(healthy)
            summary = f"selected {healthy[0]} from {len(healthy)} candidate(s)"
        else:
            summary = "no healthy candidate to select"
        return ReasoningStep(agent=self._name, summary=summary)

    async def dispose(self) -> None:
        return None
