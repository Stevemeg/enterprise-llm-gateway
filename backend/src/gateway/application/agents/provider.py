"""ProviderAgent - selects the provider a request routes to (ADR-0016 Slice 6; adaptive Slice 21).

Slices 6-20 selected the first healthy candidate. That was a placeholder its own docstring called
out ("selection intelligence ... is the routing-engine milestone"). Slice 21 makes it adaptive:
the agent gathers the **usable** candidates - healthy (closed circuits) and degraded (half-open,
recovering) - and delegates the choice to a ``RoutingStrategy``, which ranks them (ADR-0012's
ranking strategy). The agent still owns *that a provider is selected and recorded*; the strategy
owns *which one*, behind a port so a new ranking rule is a new adapter rather than a change here.

The strategy is optional. Without one wired (some tests, and any deployment that has not chosen a
strategy) the agent keeps the old first-usable behaviour - preferring healthy, then degraded - so
it is never left unable to select. When a strategy is present it decides among the usable set.

This agent never constructs a ``RoutingDecision`` (invariant 3): it writes its selection into the
shared context and the runtime builds the record. It reaches no provider client, catalog or
executor - selection is a decision, not a call.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.application.ports.routing_strategy import RoutingCandidate, RoutingStrategy
from gateway.domain.routing.models import ReasoningStep


class ProviderAgent:
    def __init__(self, name: str = "provider", *, strategy: RoutingStrategy | None = None) -> None:
        self._name = name
        self._strategy = strategy

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        health = agent_context.health
        healthy = health.healthy_candidates if health else ()
        degraded = health.degraded_candidates if health else ()

        # Usable = healthy then degraded. A degraded (half-open) provider is a valid, if
        # last-preference, choice; excluding it would leave a recovering circuit never probed.
        candidates = tuple(RoutingCandidate(provider=p, degraded=False) for p in healthy) + tuple(
            RoutingCandidate(provider=p, degraded=True) for p in degraded
        )

        selected = self._select(candidates)
        if selected is not None:
            agent_context.selected_provider = selected
            agent_context.confidence = 1.0 / len(candidates)
            tier = "degraded" if selected in degraded else "healthy"
            summary = f"selected {selected} ({tier}) from {len(candidates)} usable candidate(s)"
        else:
            summary = "no usable candidate to select"
        return ReasoningStep(agent=self._name, summary=summary)

    def _select(self, candidates: tuple[RoutingCandidate, ...]) -> str | None:
        if self._strategy is not None:
            return self._strategy.select(candidates)
        # Fallback with no strategy wired: first usable (already ordered healthy-then-degraded).
        return candidates[0].provider if candidates else None

    async def dispose(self) -> None:
        return None
