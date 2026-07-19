"""Agent lifecycle seam (ADR-0016, Tier-1 invariant 4).

Every future agent - Planner, Policy, Cost, Health, Provider, Reflection, Evaluation - shares one
lifecycle so orchestration, telemetry and testing are written once. This is the reusable surface
intended to outlive this project.

Protocol only. No agents, no orchestration (Rule 2).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from gateway.domain.routing.models import ReasoningStep


@runtime_checkable
class BaseAgent(Protocol):
    """Common lifecycle for every agent.

    ``runtime_checkable`` so CI can assert conformance structurally rather than by inheritance -
    an agent that merely *looks* like an agent but omits ``contribute`` would otherwise pass
    review unnoticed.

    ``contribute`` returns a ``ReasoningStep`` rather than a bare verdict, so an agent physically
    cannot participate in a routing decision without explaining itself.
    """

    @property
    def name(self) -> str:
        """Stable identifier recorded in reasoning steps and metrics."""
        ...

    async def prepare(self) -> None:
        """Acquire whatever the agent needs before first use. Idempotent."""
        ...

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        """Perform this agent's part of a decision and explain it."""
        ...

    async def dispose(self) -> None:
        """Release resources. Idempotent; must not raise."""
        ...
