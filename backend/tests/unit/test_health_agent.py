"""HealthAgent circuit-breaker integration (ADR-0016 Slice 20).

The agent is a pure reader of circuit state: given a breaker, an OPEN circuit must be excluded, a
CLOSED one healthy, and a HALF_OPEN one healthy-and-probing (usable, because a half-open circuit
exists precisely to let one request through). Failure-first: the exclusion path is asserted before
the healthy path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from gateway.adapters.health.in_memory_circuit_breaker import (
    CircuitBreakerConfig,
    InMemoryCircuitBreaker,
)
from gateway.application.agents.base import AgentContext
from gateway.application.agents.health import HealthAgent
from gateway.application.ports.circuit_breaker import ProviderCallResult
from gateway.application.ports.providers import ProviderErrorCategory

ORG = uuid4()


class SteppingClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


_FAULT = ProviderCallResult(ok=False, error_category=ProviderErrorCategory.SERVER_ERROR)


def _context(candidates: tuple[str, ...]) -> tuple[dict[str, object], AgentContext]:
    ctx = AgentContext(organization_id=ORG, correlation_id="c-1", candidates=candidates)
    return {"agent_context": ctx}, ctx


async def _run(agent: HealthAgent, candidates: tuple[str, ...]) -> AgentContext:
    shared, ctx = _context(candidates)
    await agent.contribute(shared)
    return ctx


async def test_an_open_circuit_is_excluded() -> None:
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(clock, CircuitBreakerConfig(failure_threshold=2))
    for _ in range(2):
        breaker.observe(organization_id=ORG, provider="down", result=_FAULT)
    ctx = await _run(HealthAgent(breaker=breaker), ("up", "down"))
    assert ctx.health is not None
    assert ctx.health.excluded_candidates == ("down",)
    assert ctx.health.healthy_candidates == ("up",)


async def test_a_half_open_circuit_is_degraded_but_usable() -> None:
    """After cooldown the provider is usable again so one request can probe it, but it is a
    DEGRADED tier (Slice 21) so the strategy prefers a healthy provider over it - not excluded,
    not fully healthy."""
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(
        clock, CircuitBreakerConfig(failure_threshold=2, cooldown=timedelta(seconds=10))
    )
    for _ in range(2):
        breaker.observe(organization_id=ORG, provider="recovering", result=_FAULT)
    clock.advance(10)
    step_shared, ctx = _context(("recovering",))
    step = await HealthAgent(breaker=breaker).contribute(step_shared)
    assert ctx.health is not None
    assert ctx.health.degraded_candidates == ("recovering",)
    assert ctx.health.healthy_candidates == ()
    assert ctx.health.excluded_candidates == ()
    assert step.detail["degraded"] == ["recovering"]


async def test_all_candidates_healthy_when_no_failures() -> None:
    clock = SteppingClock()
    breaker = InMemoryCircuitBreaker(clock)
    ctx = await _run(HealthAgent(breaker=breaker), ("a", "b"))
    assert ctx.health is not None
    assert ctx.health.healthy_candidates == ("a", "b")
    assert ctx.health.excluded_candidates == ()


async def test_without_a_breaker_the_static_fallback_is_preserved() -> None:
    """A deployment or test with no breaker wired keeps the old static behaviour - the safe
    default of trusting every candidate unless explicitly told otherwise."""
    ctx = await _run(HealthAgent(unhealthy=("bad",)), ("good", "bad"))
    assert ctx.health is not None
    assert ctx.health.healthy_candidates == ("good",)
    assert ctx.health.excluded_candidates == ("bad",)
