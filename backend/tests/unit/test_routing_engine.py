"""RoutingEngine tests (ADR-0016 Slice 6).

Fail-safe paths first. The engine's correctness is mostly about what it *declines* to do: it must
respect every denial the agents produce without softening it, and must never author an
explanation of its own.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.ports.routing import (
    RoutingEngine,
    RoutingExecution,
    RoutingIntegrityError,
)
from gateway.application.routing.catalog import (
    InMemoryProviderCatalog,
    ProviderCatalog,
    ProviderDescriptor,
)
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.domain.routing.models import RoutingDecision, RoutingOutcome

ORG = uuid4()
OTHER_ORG = uuid4()
OPENAI = ProviderDescriptor(name="openai", model="gpt-4o")
ANTHROPIC = ProviderDescriptor(name="anthropic", model="claude-sonnet")


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)


def engine(
    *,
    providers: tuple[ProviderDescriptor, ...] = (OPENAI,),
    policy_allow: bool = True,
    within_budget: bool = True,
    unhealthy: tuple[str, ...] = (),
) -> AgentOrchestratedRoutingEngine:
    runtime = AgentRuntime(
        [
            PlannerAgent(),
            PolicyAgent(allow=policy_allow, reason=None if policy_allow else "region denied"),
            CostAgent(within_budget=within_budget),
            HealthAgent(unhealthy=unhealthy),
            ProviderAgent(),
        ],
        FixedClock(),
    )
    return AgentOrchestratedRoutingEngine(InMemoryProviderCatalog({ORG: providers}), runtime)


async def route(e: AgentOrchestratedRoutingEngine, org: UUID = ORG) -> RoutingExecution:
    return await e.route(organization_id=org, correlation_id="corr-1")


# ------------------------------------------------------------------ fail-safe paths first


async def test_no_provider_available_is_an_explained_denial_not_an_error() -> None:
    execution = await route(engine(providers=()))
    assert execution.decision.outcome is RoutingOutcome.NO_CANDIDATE
    assert execution.provider is None
    assert execution.routed is False
    assert execution.decision.reasoning_steps  # still explained


async def test_policy_denial_is_respected_and_never_softened() -> None:
    execution = await route(engine(policy_allow=False))
    assert execution.decision.outcome is RoutingOutcome.BLOCKED_BY_POLICY
    assert execution.provider is None
    assert execution.decision.policy_result is not None
    assert execution.decision.policy_result.allowed is False


async def test_budget_denial_is_respected() -> None:
    execution = await route(engine(within_budget=False))
    assert execution.decision.outcome is RoutingOutcome.BUDGET_EXCEEDED
    assert execution.provider is None


async def test_all_unhealthy_providers_deny() -> None:
    execution = await route(engine(unhealthy=("openai",)))
    assert execution.decision.outcome is RoutingOutcome.ALL_UNHEALTHY
    assert execution.provider is None


async def test_another_tenant_sees_an_empty_catalog() -> None:
    execution = await route(engine(), org=OTHER_ORG)
    assert execution.decision.outcome is RoutingOutcome.NO_CANDIDATE
    assert execution.provider is None


async def test_catalog_disagreement_raises_instead_of_faking_a_denial() -> None:
    """A defect must not enter the decision record dressed as an explained outcome."""

    class LyingCatalog(InMemoryProviderCatalog):
        """Lists a provider but refuses to resolve it - the engine and catalog disagreeing."""

        async def get(self, organization_id: UUID, name: str) -> ProviderDescriptor | None:
            return None

    runtime = AgentRuntime(
        [PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()], FixedClock()
    )
    broken = AgentOrchestratedRoutingEngine(LyingCatalog({ORG: (OPENAI,)}), runtime)
    with pytest.raises(RoutingIntegrityError):
        await route(broken)


# ------------------------------------------------------------------ success


async def test_successful_routing_resolves_the_selected_provider() -> None:
    execution = await route(engine())
    assert execution.decision.outcome is RoutingOutcome.SELECTED
    assert execution.provider == OPENAI
    assert execution.routed is True
    assert execution.decision.selected_provider == "openai"


async def test_ambiguous_candidates_are_resolved_by_the_agents_not_the_engine() -> None:
    execution = await route(engine(providers=(OPENAI, ANTHROPIC)))
    assert execution.decision.outcome is RoutingOutcome.SELECTED
    # Ambiguity is reported through confidence by ProviderAgent; the engine must not re-rank.
    assert execution.decision.confidence == pytest.approx(0.5)
    assert execution.provider in (OPENAI, ANTHROPIC)


# ------------------------------------------------------------------ explanation invariants


async def test_routing_decision_is_the_only_explanation_object() -> None:
    """RoutingExecution carries no reason, message or status of its own."""
    fields = {f.name for f in dataclasses.fields(RoutingExecution)}
    assert fields == {"decision", "provider"}


async def test_routing_decision_is_immutable() -> None:
    execution = await route(engine())
    with pytest.raises(dataclasses.FrozenInstanceError):
        execution.decision.outcome = RoutingOutcome.NO_CANDIDATE  # type: ignore[misc]


async def test_engine_never_invents_reasoning_steps() -> None:
    """Every step is authored by an agent; the engine contributes none."""
    execution = await route(engine())
    authors = {step.agent for step in execution.decision.reasoning_steps}
    assert authors == {"planner", "policy", "cost", "health", "provider"}


async def test_decision_originates_from_the_runtime() -> None:
    execution = await route(engine())
    assert isinstance(execution.decision, RoutingDecision)
    # The clock is the runtime's, not the engine's - proof of authorship.
    assert execution.decision.decided_at == FixedClock().now()


async def test_engine_and_catalog_satisfy_their_ports() -> None:
    assert isinstance(engine(), RoutingEngine)
    assert isinstance(InMemoryProviderCatalog(), ProviderCatalog)
