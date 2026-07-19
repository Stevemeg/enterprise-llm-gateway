"""HealthAgent (stub) - treats every candidate as healthy.

Circuit-breaker state and provider health snapshots arrive with the provider milestone. The stub
lets the runtime's all-unhealthy short-circuit be tested by configuring it to exclude candidates.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.domain.routing.models import HealthDecision, ReasoningStep


class HealthAgent:
    def __init__(self, name: str = "health", *, unhealthy: tuple[str, ...] = ()) -> None:
        self._name = name
        self._unhealthy = unhealthy

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        healthy = tuple(c for c in agent_context.candidates if c not in self._unhealthy)
        excluded = tuple(c for c in agent_context.candidates if c in self._unhealthy)
        agent_context.health = HealthDecision(
            healthy_candidates=healthy, excluded_candidates=excluded
        )
        return ReasoningStep(
            agent=self._name,
            summary=f"{len(healthy)} healthy, {len(excluded)} excluded",
            detail={"healthy": list(healthy), "excluded": list(excluded)},
        )

    async def dispose(self) -> None:
        return None
