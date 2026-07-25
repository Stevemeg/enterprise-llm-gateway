"""Health-tiered routing strategy and ProviderAgent delegation (ADR-0016 Slice 21).

The strategy is a pure, deterministic ranking function; the ProviderAgent turns the health tiers
into candidates and records the strategy's choice. Failure-first: the ways selection could pick a
worse (degraded) provider when a healthy one exists, or become non-deterministic, are asserted
before the happy path.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from gateway.application.agents.base import AgentContext
from gateway.application.agents.provider import ProviderAgent
from gateway.application.ports.routing_strategy import RoutingCandidate
from gateway.application.routing.health_tiered_strategy import HealthTieredRoutingStrategy
from gateway.domain.routing.models import HealthDecision

ORG = uuid4()
_STRATEGY = HealthTieredRoutingStrategy()


# ------------------------------------------------------------------ the strategy


def test_an_empty_candidate_set_selects_nothing() -> None:
    assert _STRATEGY.select(()) is None


def test_a_healthy_candidate_is_preferred_over_a_degraded_one() -> None:
    """The core of adaptive routing: a recovering provider is not chosen while a healthy one is
    available, regardless of input order."""
    chosen = _STRATEGY.select(
        (
            RoutingCandidate(provider="recovering", degraded=True),
            RoutingCandidate(provider="healthy", degraded=False),
        )
    )
    assert chosen == "healthy"


def test_a_degraded_candidate_is_chosen_when_it_is_the_only_usable_one() -> None:
    """A half-open provider must still be probed when nothing healthy exists - excluding it would
    leave its circuit never able to recover."""
    assert _STRATEGY.select((RoutingCandidate(provider="only", degraded=True),)) == "only"


def test_ties_break_deterministically_by_name() -> None:
    """Two healthy providers must resolve to the same choice on every replay (FR-033)."""
    first = _STRATEGY.select(
        (RoutingCandidate(provider="zeta"), RoutingCandidate(provider="alpha"))
    )
    second = _STRATEGY.select(
        (RoutingCandidate(provider="alpha"), RoutingCandidate(provider="zeta"))
    )
    assert first == second == "alpha"


def test_the_tiebreak_does_not_override_the_tier() -> None:
    """A name-earlier degraded provider must NOT beat a name-later healthy one: tier dominates."""
    chosen = _STRATEGY.select(
        (
            RoutingCandidate(provider="aaa", degraded=True),
            RoutingCandidate(provider="zzz", degraded=False),
        )
    )
    assert chosen == "zzz"


# ------------------------------------------------------------------ ProviderAgent delegation


def _context(health: HealthDecision) -> tuple[dict[str, Any], AgentContext]:
    ctx = AgentContext(organization_id=ORG, correlation_id="c-1", candidates=("a", "b"))
    ctx.health = health
    return {"agent_context": ctx}, ctx


async def test_the_provider_agent_selects_via_the_strategy() -> None:
    shared, ctx = _context(
        HealthDecision(healthy_candidates=("healthy",), degraded_candidates=("recovering",))
    )
    await ProviderAgent(strategy=_STRATEGY).contribute(shared)
    assert ctx.selected_provider == "healthy"


async def test_the_provider_agent_can_select_a_degraded_provider_when_alone() -> None:
    shared, ctx = _context(HealthDecision(degraded_candidates=("recovering",)))
    step = await ProviderAgent(strategy=_STRATEGY).contribute(shared)
    assert ctx.selected_provider == "recovering"
    assert "degraded" in step.summary


async def test_the_provider_agent_selects_nothing_when_no_candidate_is_usable() -> None:
    shared, ctx = _context(HealthDecision(excluded_candidates=("down",)))
    step = await ProviderAgent(strategy=_STRATEGY).contribute(shared)
    assert ctx.selected_provider is None
    assert "no usable candidate" in step.summary


async def test_without_a_strategy_the_provider_agent_falls_back_to_first_usable() -> None:
    """The no-strategy path (some tests, unwired deployments) still selects - preferring healthy,
    then degraded - so it is never left unable to route."""
    shared, ctx = _context(
        HealthDecision(healthy_candidates=("first", "second"), degraded_candidates=("third",))
    )
    await ProviderAgent().contribute(shared)
    assert ctx.selected_provider == "first"
