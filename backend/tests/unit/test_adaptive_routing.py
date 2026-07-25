"""Adaptive routing end to end through the real runtime (ADR-0016 Slice 21).

Proves the composition Slice 20 + Slice 21 produce: a live circuit-health signal (Slice 20) that
the strategy ranks on (Slice 21), so routing adapts to which providers are actually healthy. Uses
the real ``AgentRuntime``, ``HealthAgent`` (breaker-backed) and ``ProviderAgent`` (strategy-backed)
- no doubles for the parts under test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from gateway.adapters.health.in_memory_circuit_breaker import (
    CircuitBreakerConfig,
    InMemoryCircuitBreaker,
)
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.ports.circuit_breaker import ProviderCallResult
from gateway.application.ports.providers import ProviderErrorCategory
from gateway.application.routing.health_tiered_strategy import HealthTieredRoutingStrategy
from gateway.domain.routing.models import RoutingDecision, RoutingOutcome

ORG = uuid4()
_FAULT = ProviderCallResult(ok=False, error_category=ProviderErrorCategory.SERVER_ERROR)


class SteppingClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _runtime(breaker: InMemoryCircuitBreaker, clock: SteppingClock) -> AgentRuntime:
    return AgentRuntime(
        [
            PlannerAgent(),
            PolicyAgent(),
            CostAgent(),
            HealthAgent(breaker=breaker),
            ProviderAgent(strategy=HealthTieredRoutingStrategy()),
        ],
        clock,
    )


async def _decide(runtime: AgentRuntime, candidates: tuple[str, ...]) -> RoutingDecision:
    return await runtime.decide(
        organization_id=ORG,
        correlation_id="c-1",
        request={"modality": "chat", "prompt": "hello"},
        candidates=candidates,
    )


async def test_routing_avoids_a_provider_whose_circuit_has_opened() -> None:
    """The headline: after a provider's circuit trips, routing selects a healthy alternative."""
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(clock, CircuitBreakerConfig(failure_threshold=2))
    for _ in range(2):
        breaker.observe(organization_id=ORG, provider="flaky", result=_FAULT)

    decision = await _decide(_runtime(breaker, clock), ("flaky", "solid"))

    assert decision.outcome is RoutingOutcome.SELECTED
    assert decision.selected_provider == "solid", "the open circuit must be routed around"
    assert decision.health_result is not None
    assert "flaky" in decision.health_result.excluded_candidates


async def test_routing_prefers_a_healthy_provider_over_a_recovering_one() -> None:
    """A half-open (degraded) provider is usable but deprioritized: a healthy peer wins."""
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(
        clock, CircuitBreakerConfig(failure_threshold=2, cooldown=timedelta(seconds=10))
    )
    for _ in range(2):
        breaker.observe(organization_id=ORG, provider="recovering", result=_FAULT)
    clock.advance(10)  # -> HALF_OPEN on the next assess

    decision = await _decide(_runtime(breaker, clock), ("recovering", "healthy"))

    assert decision.selected_provider == "healthy"
    assert decision.health_result is not None
    assert decision.health_result.degraded_candidates == ("recovering",)


async def test_a_recovering_provider_is_still_probed_when_it_is_the_only_option() -> None:
    """A half-open provider alone is routable (not ALL_UNHEALTHY) - it gets the probe it needs."""
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(
        clock, CircuitBreakerConfig(failure_threshold=2, cooldown=timedelta(seconds=10))
    )
    for _ in range(2):
        breaker.observe(organization_id=ORG, provider="recovering", result=_FAULT)
    clock.advance(10)

    decision = await _decide(_runtime(breaker, clock), ("recovering",))

    assert decision.outcome is RoutingOutcome.SELECTED
    assert decision.selected_provider == "recovering"


async def test_all_circuits_open_is_all_unhealthy() -> None:
    """When nothing is usable - every circuit open, none half-open - routing refuses explainably."""
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(clock, CircuitBreakerConfig(failure_threshold=2))
    for provider in ("a", "b"):
        for _ in range(2):
            breaker.observe(organization_id=ORG, provider=provider, result=_FAULT)

    decision = await _decide(_runtime(breaker, clock), ("a", "b"))

    assert decision.outcome is RoutingOutcome.ALL_UNHEALTHY
    assert decision.selected_provider is None
