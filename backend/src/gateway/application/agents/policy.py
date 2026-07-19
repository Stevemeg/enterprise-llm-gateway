"""PolicyAgent (stub) - allows everything, explains that it did.

A stub that *allows* is the safe shape here only because no request reaches a provider in this
slice. When the OPA policy stage lands it becomes a pipeline stage (invariant 5); this agent
exists now to validate the orchestration contract and the short-circuit path.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.domain.routing.models import PolicyDecision, ReasoningStep


class PolicyAgent:
    def __init__(
        self, name: str = "policy", *, allow: bool = True, reason: str | None = None
    ) -> None:
        self._name = name
        self._allow = allow
        self._reason = reason

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        agent_context.policy = PolicyDecision(allowed=self._allow, reason=self._reason)
        summary = "allowed" if self._allow else f"denied: {self._reason or 'policy'}"
        return ReasoningStep(agent=self._name, summary=summary)

    async def dispose(self) -> None:
        return None
