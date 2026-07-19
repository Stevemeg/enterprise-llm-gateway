"""PlannerAgent - classifies what the request needs.

The only agent in this slice with real (if simple) logic: it derives intent and complexity from
the request so later agents and tests have something non-trivial to work with. Deliberately
heuristic - genuine intent detection belongs to the adaptive-routing milestone.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.domain.routing.models import PlannerDecision, ReasoningStep

_LONG_PROMPT_CHARS = 2000


class PlannerAgent:
    """Determines intent, complexity and required capabilities."""

    def __init__(self, name: str = "planner") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        request = agent_context.request

        modality = str(request.get("modality", "chat"))
        prompt = str(request.get("prompt", ""))
        complexity = "high" if len(prompt) >= _LONG_PROMPT_CHARS else "low"
        capabilities = (modality,) if modality else ()

        agent_context.planner = PlannerDecision(
            intent=modality, complexity=complexity, required_capabilities=capabilities
        )
        return ReasoningStep(
            agent=self._name,
            summary=f"intent={modality} complexity={complexity}",
            detail={"prompt_chars": len(prompt), "capabilities": list(capabilities)},
        )

    async def dispose(self) -> None:
        return None
