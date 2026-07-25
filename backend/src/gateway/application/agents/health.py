"""HealthAgent - reports which candidates are currently usable (ADR-0016 Slice 20).

Until Slice 20 this was a stub that treated every candidate as healthy unless a static
``unhealthy`` set said otherwise. It now consults a ``CircuitBreaker`` for the live circuit state
of each candidate and translates that into the ``HealthDecision`` the runtime already consumes:

* **CLOSED** circuit  -> healthy candidate;
* **HALF_OPEN** circuit -> **degraded** candidate: usable (its cooldown elapsed, so one request may
  probe recovery) but recovering, so ranked behind a fully healthy provider;
* **OPEN** circuit    -> excluded candidate (still failing; skip it until it half-opens).

Both healthy and degraded candidates are **usable** - the difference is preference, not
eligibility. Slice 20 shipped this agent putting half-open circuits in ``healthy_candidates`` and
recording the probe only in the reasoning, because nothing yet *ranked* candidates and the
healthy/degraded distinction had no consumer (Rule 8). Slice 21's adaptive-routing strategy is
that consumer, so the distinction becomes structural: a half-open circuit is now ``degraded``, and
the strategy prefers healthy over it.

## Why a breaker rather than continuing to read a static set

The static set could only ever encode a human's guess about what is down. The breaker encodes what
actually happened: a provider that just returned five timeouts is excluded automatically, and
re-admitted automatically once it recovers. The agent stays a pure *reader* of that state - it
never records outcomes itself (that is the execution coordinator's job, after a real call), so the
routing-time read and the execution-time write cannot be confused.

The ``breaker`` is optional so a deployment or test without circuit breaking wired keeps the old
static behaviour (the safe default: an unconfigured breaker means "trust every candidate", the
same posture as an empty provider catalog). When a breaker is present it is authoritative and the
static ``unhealthy`` set is ignored.
"""

from __future__ import annotations

from typing import Any

from gateway.application.agents.base import AgentContext
from gateway.application.ports.circuit_breaker import CircuitBreaker, CircuitState
from gateway.domain.routing.models import HealthDecision, ReasoningStep


class HealthAgent:
    def __init__(
        self,
        name: str = "health",
        *,
        breaker: CircuitBreaker | None = None,
        unhealthy: tuple[str, ...] = (),
    ) -> None:
        self._name = name
        self._breaker = breaker
        self._unhealthy = unhealthy

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        return None

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        agent_context: AgentContext = context["agent_context"]
        candidates = agent_context.candidates

        if self._breaker is None:
            healthy = tuple(c for c in candidates if c not in self._unhealthy)
            excluded = tuple(c for c in candidates if c in self._unhealthy)
            degraded: tuple[str, ...] = ()
        else:
            healthy, degraded, excluded = self._assess(agent_context, candidates)

        agent_context.health = HealthDecision(
            healthy_candidates=healthy,
            degraded_candidates=degraded,
            excluded_candidates=excluded,
        )
        summary = f"{len(healthy)} healthy, {len(degraded)} degraded, {len(excluded)} excluded"
        return ReasoningStep(
            agent=self._name,
            summary=summary,
            detail={
                "healthy": list(healthy),
                "degraded": list(degraded),
                "excluded": list(excluded),
            },
        )

    def _assess(
        self, agent_context: AgentContext, candidates: tuple[str, ...]
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        assert self._breaker is not None
        assessments = self._breaker.assess(
            organization_id=agent_context.organization_id, providers=candidates
        )
        healthy: list[str] = []
        degraded: list[str] = []
        excluded: list[str] = []
        for assessment in assessments:
            if assessment.state is CircuitState.OPEN:
                excluded.append(assessment.provider)
            elif assessment.state is CircuitState.HALF_OPEN:
                degraded.append(assessment.provider)
            else:
                healthy.append(assessment.provider)
        return tuple(healthy), tuple(degraded), tuple(excluded)

    async def dispose(self) -> None:
        return None
