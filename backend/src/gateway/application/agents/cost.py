"""CostAgent (stub) - reports a fixed estimate.

Real estimation needs the price table and budget ledger (ADR-0004); neither is wired in this
slice. The stub exists so the runtime's assembly of ``CostDecision`` is exercised.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.domain.routing.models import CostDecision, ReasoningStep


class CostAgent:
    def __init__(
        self, name: str = "cost", *, estimated_cost: float = 0.0, within_budget: bool = True
    ) -> None:
        self._name = name
        self._estimated_cost = estimated_cost
        self._within_budget = within_budget

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        agent_context.cost = CostDecision(
            estimated_cost=self._estimated_cost, within_budget=self._within_budget
        )
        verdict = "within budget" if self._within_budget else "budget exceeded"
        return ReasoningStep(
            agent=self._name,
            summary=f"estimate={self._estimated_cost} ({verdict})",
            detail={"estimated_cost": self._estimated_cost},
        )

    async def dispose(self) -> None:
        return None
