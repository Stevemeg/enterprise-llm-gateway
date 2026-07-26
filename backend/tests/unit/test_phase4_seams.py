"""Phase-4 architectural seams: conformance and behaviour (ADR-0016).

These seams are production code, so they carry tests like any other. Two jobs here:

1. **Protocol conformance.** import-linter checks *dependencies*; it cannot check that a class
   actually satisfies a Protocol. Structural typing fails silently - a class missing a method
   still imports fine and only breaks at the call site. These tests are the enforcement mechanism
   for Tier-1 invariants 4 and 5.
2. **Behaviour the protocol alone does not pin down.** Writing InMemoryToolRegistry forced two
   decisions the interface left open (unversioned resolution, permission failure direction).
   That is Rule 4 working, and those decisions are pinned here so they cannot drift.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from gateway.adapters.agents.skeleton import BaseAgentSkeleton
from gateway.adapters.mcp.null_gateway import NullMcpGateway
from gateway.adapters.pipeline.noop_stage import NoOpPipelineStage
from gateway.adapters.tools.in_memory_registry import InMemoryToolRegistry
from gateway.application.ports.agents import BaseAgent
from gateway.application.ports.mcp import McpInvocation, McpResult
from gateway.application.ports.pipeline import StageAction, StageContext, StageResult
from gateway.application.ports.tools import ToolDescriptor
from gateway.domain.routing.models import (
    CostDecision,
    HealthDecision,
    PlannerDecision,
    PolicyDecision,
    ReasoningStep,
    RoutingDecision,
    RoutingOutcome,
)

# --- protocol conformance -------------------------------------------------------------------


def test_skeleton_agent_satisfies_the_base_agent_protocol() -> None:
    """Structural conformance fails silently; assert it explicitly."""
    assert isinstance(BaseAgentSkeleton(), BaseAgent)


@pytest.mark.parametrize(
    "implementation",
    [NoOpPipelineStage(), NullMcpGateway(), InMemoryToolRegistry(), BaseAgentSkeleton()],
)
def test_validation_implementations_expose_their_required_surface(implementation: object) -> None:
    """Every Rule-4 implementation must expose the methods its seam declares."""
    required = {
        "NoOpPipelineStage": ("name", "before_request"),
        "NullMcpGateway": ("discover", "execute", "health"),
        "InMemoryToolRegistry": ("register", "get", "discover", "permitted"),
        "BaseAgentSkeleton": ("name", "prepare", "contribute", "dispose"),
    }[type(implementation).__name__]
    for attribute in required:
        assert hasattr(implementation, attribute), f"missing {attribute}"


async def test_agent_lifecycle_is_idempotent_and_contributes_reasoning() -> None:
    agent = BaseAgentSkeleton("planner-stub")
    await agent.prepare()
    await agent.prepare()
    assert agent.prepared is True

    step = await agent.contribute({})
    # An agent cannot participate without explaining itself (invariant 3).
    assert isinstance(step, ReasoningStep)
    assert step.agent == "planner-stub"
    assert step.summary

    await agent.dispose()
    await agent.dispose()
    assert agent.prepared is False


# --- pipeline stage -------------------------------------------------------------------------


async def test_noop_stage_always_continues() -> None:
    stage = NoOpPipelineStage()
    context = StageContext(correlation_id="c-1")
    assert stage.name == "noop"
    result = await stage.before_request(context)
    assert result.action is StageAction.CONTINUE
    assert result.blocked is False


def test_stage_result_supports_continue_annotate_and_block() -> None:
    assert StageResult().action is StageAction.CONTINUE
    annotated = StageResult(action=StageAction.ANNOTATE, annotations={"pii": True})
    assert annotated.annotations["pii"] is True
    assert annotated.blocked is False
    blocked = StageResult(action=StageAction.BLOCK, reason="policy denied")
    assert blocked.blocked is True
    assert blocked.reason == "policy denied"


# --- MCP gateway ----------------------------------------------------------------------------


async def test_null_mcp_gateway_reports_failure_as_data_not_exceptions() -> None:
    gateway = NullMcpGateway()
    assert await gateway.discover() == ()

    result = await gateway.execute(McpInvocation(tool="github.search"))
    assert result.ok is False
    assert result.error is not None  # callers must be able to fail closed on this

    health = await gateway.health()
    assert health.healthy is False


def test_mcp_result_distinguishes_success_from_failure() -> None:
    assert McpResult(ok=True, content={"rows": 1}).ok is True
    assert McpResult(ok=False, error="unreachable").content is None


# --- tool registry: behaviour the protocol left open ------------------------------------------


def _tool(name: str, version: str, **kwargs: object) -> ToolDescriptor:
    return ToolDescriptor(name=name, version=version, description="t", **kwargs)  # type: ignore[arg-type]


async def test_registry_registers_and_resolves_by_explicit_version() -> None:
    registry = InMemoryToolRegistry()
    await registry.register(_tool("github", "1.0.0"))
    found = await registry.get("github", "1.0.0")
    assert found is not None
    assert found.qualified_name == "github@1.0.0"


async def test_unversioned_lookup_returns_the_newest_version() -> None:
    """Rule 4 discovery: the protocol did not say which version an unversioned get() returns."""
    registry = InMemoryToolRegistry()
    await registry.register(_tool("github", "1.0.0"))
    await registry.register(_tool("github", "2.0.0"))
    newest = await registry.get("github")
    assert newest is not None
    assert newest.version == "2.0.0"


async def test_registering_the_same_qualified_name_replaces_it() -> None:
    registry = InMemoryToolRegistry()
    await registry.register(_tool("github", "1.0.0", capabilities=("search",)))
    await registry.register(_tool("github", "1.0.0", capabilities=("search", "issues")))
    found = await registry.get("github", "1.0.0")
    assert found is not None
    assert found.capabilities == ("search", "issues")


async def test_missing_tool_resolves_to_none_so_callers_fail_closed() -> None:
    assert await InMemoryToolRegistry().get("nope") is None


async def test_discovery_requires_every_requested_capability() -> None:
    registry = InMemoryToolRegistry()
    await registry.register(_tool("github", "1.0.0", capabilities=("search", "issues")))
    await registry.register(_tool("slack", "1.0.0", capabilities=("search",)))

    assert len(await registry.discover()) == 2
    assert len(await registry.discover(capabilities=("search",))) == 2
    both = await registry.discover(capabilities=("search", "issues"))
    assert [d.name for d in both] == ["github"]


async def test_permission_check_fails_closed() -> None:
    """Rule 4 discovery: missing permissions must deny, never default to allow."""
    registry = InMemoryToolRegistry()
    tool = _tool("github", "1.0.0", required_permissions=("tool:github", "repo:read"))

    assert await registry.permitted(tool, frozenset()) is False
    assert await registry.permitted(tool, frozenset({"tool:github"})) is False
    assert await registry.permitted(tool, frozenset({"tool:github", "repo:read"})) is True
    # A tool requiring nothing is permitted to anyone.
    assert await registry.permitted(_tool("open", "1.0.0"), frozenset()) is True


# --- routing decision -----------------------------------------------------------------------


def _decision(*steps: ReasoningStep) -> RoutingDecision:
    return RoutingDecision(
        outcome=RoutingOutcome.SELECTED,
        organization_id=uuid4(),
        correlation_id="c-1",
        decided_at=datetime.now(UTC),
        reasoning_steps=steps,
        selected_provider="openai",
        planner_result=PlannerDecision(intent="chat", complexity="low"),
        policy_result=PolicyDecision(allowed=True),
        cost_result=CostDecision(estimated_cost=0.01),
        health_result=HealthDecision(healthy_candidates=("openai",)),
    )


def test_routing_decision_is_immutable() -> None:
    """Downstream code must not be able to rewrite a decision after the fact."""
    decision = _decision(ReasoningStep(agent="planner", summary="chat"))
    with pytest.raises((FrozenInstanceError, AttributeError)):
        decision.selected_provider = "anthropic"  # type: ignore[misc]


def test_routing_decision_preserves_reasoning_and_reports_agents() -> None:
    decision = _decision(
        ReasoningStep(agent="planner", summary="intent=chat"),
        ReasoningStep(agent="policy", summary="allowed"),
        ReasoningStep(agent="cost", summary="within budget"),
        ReasoningStep(agent="policy", summary="region ok"),
    )
    assert len(decision.reasoning_steps) == 4
    # Distinct, order-preserving - the basis of the completeness check.
    assert decision.agents_consulted() == ("planner", "policy", "cost")
    assert decision.is_selection is True


def test_a_non_selection_is_not_reported_as_a_selection() -> None:
    blocked = RoutingDecision(
        outcome=RoutingOutcome.BLOCKED_BY_POLICY,
        organization_id=uuid4(),
        correlation_id="c-2",
        decided_at=datetime.now(UTC),
        reasoning_steps=(ReasoningStep(agent="policy", summary="region not permitted"),),
    )
    assert blocked.is_selection is False
    assert blocked.selected_provider is None


def test_every_decision_carries_reasoning() -> None:
    """Invariant 3: a decision with no recorded reasoning is unexplainable by construction."""
    decision = _decision(ReasoningStep(agent="planner", summary="chat"))
    assert decision.reasoning_steps, "reasoning_steps must never be empty"
    assert all(step.summary for step in decision.reasoning_steps)
