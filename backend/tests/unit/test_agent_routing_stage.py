"""AgentRoutingStage - the first real consumer of the PipelineStage seam (ADR-0016)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gateway.adapters.pipeline.routing_stage import ROUTING_DECISION_KEY, AgentRoutingStage
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.ports.pipeline import PipelineStage, StageAction, StageContext
from gateway.domain.routing.models import RoutingDecision, RoutingOutcome


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 19, 12, 0, 0, tzinfo=UTC)


def _stage(*, policy_allow: bool = True) -> AgentRoutingStage:
    runtime = AgentRuntime(
        [
            PlannerAgent(),
            PolicyAgent(allow=policy_allow, reason=None if policy_allow else "region denied"),
            CostAgent(),
            HealthAgent(),
            ProviderAgent(),
        ],
        FixedClock(),
    )
    return AgentRoutingStage(runtime)


def _context(**attributes: object) -> StageContext:
    return StageContext(
        correlation_id="corr-1", organization_id=uuid4(), attributes=dict(attributes)
    )


def test_stage_satisfies_the_pipeline_stage_protocol() -> None:
    assert isinstance(_stage(), PipelineStage)


async def test_selection_annotates_the_pipeline_with_the_decision() -> None:
    result = await _stage().before_request(_context(candidates=("openai",)))

    assert result.action is StageAction.ANNOTATE
    assert result.blocked is False
    decision = result.annotations[ROUTING_DECISION_KEY]
    assert isinstance(decision, RoutingDecision)
    assert decision.is_selection is True
    assert decision.selected_provider == "openai"


async def test_non_selection_is_transported_not_adjudicated() -> None:
    """The stage never blocks: a denial is annotated exactly like a selection.

    Deciding what a non-selection means belongs to later stages (Policy, Evaluation), not to the
    seam's first consumer. Downstream therefore needs no special case for a rejected decision.
    """
    result = await _stage(policy_allow=False).before_request(_context(candidates=("openai",)))

    assert result.action is StageAction.ANNOTATE
    assert result.blocked is False
    decision = result.annotations[ROUTING_DECISION_KEY]
    assert decision.outcome is RoutingOutcome.BLOCKED_BY_POLICY
    assert decision.reasoning_steps


async def test_missing_tenant_context_transports_nothing_and_does_not_block() -> None:
    result = await _stage().before_request(StageContext(correlation_id="c", organization_id=None))
    assert result.blocked is False
    assert ROUTING_DECISION_KEY not in result.annotations


async def test_after_response_and_on_error_are_inert() -> None:
    """The stage adds no post-response or error behaviour in this slice."""
    stage = _stage()
    context = _context()
    assert (await stage.after_response(context)).action is StageAction.CONTINUE
    assert (await stage.on_error(context, RuntimeError("x"))).action is StageAction.CONTINUE


def test_stage_exposes_a_stable_name() -> None:
    assert _stage().name == "agent_routing"
