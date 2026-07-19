"""AgentRuntime orchestration (ADR-0016 invariant 3).

The property under test is not "routing works" - there is no routing intelligence yet. It is
that **every** outcome, including every rejection, arrives as a fully explainable
``RoutingDecision`` built solely by the runtime.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.ports.agents import BaseAgent
from gateway.domain.routing.models import ReasoningStep, RoutingDecision, RoutingOutcome


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)


def _runtime(
    *, policy_allow: bool = True, within_budget: bool = True, unhealthy: tuple[str, ...] = ()
) -> AgentRuntime:
    return AgentRuntime(
        [
            PlannerAgent(),
            PolicyAgent(allow=policy_allow, reason=None if policy_allow else "region denied"),
            CostAgent(estimated_cost=0.02, within_budget=within_budget),
            HealthAgent(unhealthy=unhealthy),
            ProviderAgent(),
        ],
        FixedClock(),
    )


async def _decide(runtime: AgentRuntime, **kwargs: Any) -> RoutingDecision:
    return await runtime.decide(
        organization_id=uuid4(),
        correlation_id="corr-1",
        request={"modality": "chat", "prompt": "hello"},
        **kwargs,
    )


async def test_happy_path_selects_a_provider_with_full_reasoning() -> None:
    decision = await _decide(_runtime(), candidates=("openai", "anthropic"))

    assert decision.outcome is RoutingOutcome.SELECTED
    assert decision.is_selection is True
    assert decision.selected_provider == "openai"
    assert decision.agents_consulted() == ("planner", "policy", "cost", "health", "provider")
    assert decision.planner_result is not None
    assert decision.policy_result is not None
    assert decision.cost_result is not None
    assert decision.health_result is not None
    assert decision.confidence is not None


async def test_policy_denial_short_circuits_but_stays_explainable() -> None:
    decision = await _decide(_runtime(policy_allow=False), candidates=("openai",))

    assert decision.outcome is RoutingOutcome.BLOCKED_BY_POLICY
    assert decision.selected_provider is None
    # Stopped after policy - cost/health/provider never ran.
    assert decision.agents_consulted() == ("planner", "policy")
    assert decision.reasoning_steps, "a rejection must still explain itself"
    assert decision.policy_result is not None
    assert decision.policy_result.allowed is False


async def test_budget_exceeded_short_circuits_after_cost() -> None:
    decision = await _decide(_runtime(within_budget=False), candidates=("openai",))

    assert decision.outcome is RoutingOutcome.BUDGET_EXCEEDED
    assert decision.selected_provider is None
    assert decision.agents_consulted() == ("planner", "policy", "cost")


async def test_all_candidates_unhealthy_short_circuits_after_health() -> None:
    decision = await _decide(_runtime(unhealthy=("openai",)), candidates=("openai",))

    assert decision.outcome is RoutingOutcome.ALL_UNHEALTHY
    assert decision.selected_provider is None
    assert decision.agents_consulted() == ("planner", "policy", "cost", "health")


async def test_no_candidates_yields_no_candidate_not_a_selection() -> None:
    decision = await _decide(_runtime(), candidates=())

    assert decision.outcome is RoutingOutcome.NO_CANDIDATE
    assert decision.is_selection is False
    assert decision.selected_provider is None
    # The whole chain still ran and still explained itself.
    assert len(decision.agents_consulted()) == 5


async def test_every_outcome_carries_non_empty_reasoning() -> None:
    """The invariant, asserted across every terminal state rather than the happy path only."""
    cases = [
        _runtime(),
        _runtime(policy_allow=False),
        _runtime(within_budget=False),
        _runtime(unhealthy=("openai",)),
    ]
    for runtime in cases:
        decision = await _decide(runtime, candidates=("openai",))
        assert decision.reasoning_steps, f"{decision.outcome} produced no reasoning"
        assert all(step.summary for step in decision.reasoning_steps)


async def test_planner_marks_long_prompts_as_high_complexity() -> None:
    runtime = _runtime()
    decision = await runtime.decide(
        organization_id=uuid4(),
        correlation_id="corr-2",
        request={"modality": "chat", "prompt": "x" * 2500},
        candidates=("openai",),
    )
    assert decision.planner_result is not None
    assert decision.planner_result.complexity == "high"


async def test_runtime_rejects_an_empty_agent_chain() -> None:
    """An empty chain would produce a decision with no reasoning - forbidden by construction."""
    with pytest.raises(ValueError, match="at least one agent"):
        AgentRuntime([], FixedClock())


async def test_prepare_is_idempotent_and_dispose_resets() -> None:
    class CountingAgent:
        def __init__(self) -> None:
            self.prepares = 0
            self.disposes = 0

        @property
        def name(self) -> str:
            return "counter"

        async def prepare(self) -> None:
            self.prepares += 1

        async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
            return ReasoningStep(agent="counter", summary="ok")

        async def dispose(self) -> None:
            self.disposes += 1

    agent = CountingAgent()
    runtime = AgentRuntime([agent], FixedClock())
    await runtime.prepare()
    await runtime.prepare()
    await runtime.decide(organization_id=uuid4(), correlation_id="c")
    assert agent.prepares == 1

    await runtime.dispose()
    assert agent.disposes == 1


def test_all_shipped_agents_satisfy_the_base_agent_protocol() -> None:
    for agent in (PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()):
        assert isinstance(agent, BaseAgent), f"{type(agent).__name__} is not a BaseAgent"


async def test_decision_timestamp_comes_from_the_injected_clock() -> None:
    decision = await _decide(_runtime(), candidates=("openai",))
    assert decision.decided_at == FixedClock().now()
