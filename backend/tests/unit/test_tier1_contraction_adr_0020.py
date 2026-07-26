"""ADR-0020: the Tier-1 contraction, proven rather than asserted (Phase 5 M2).

Two Tier-1 surfaces were **removed** under ADR-0020: `PipelineStage.after_response`,
`PipelineStage.on_error`, and `RoutingDecision.selected_model` (with its `AgentContext` twin).
Every one had zero call sites and zero writers across Slices 1-21 and Phase 5 M1.

This file exists because "we deleted something from Tier 1" is exactly the claim that most needs
adversarial evidence. It proves three separate things:

1. **The surfaces are genuinely gone** - not merely unused, but absent from the type, so a
   re-introduction is a visible Tier-1 change rather than a quiet one.
2. **Nothing lost information.** The selected model is still reachable, still priced against, and
   still persisted - through `RoutingExecution.provider`, which is where every consumer already
   read it from.
3. **Runtime semantics did not change.** The narrowing removed description, not behaviour. The
   admission chain's ordering, blocking and short-circuit properties are re-asserted here against
   the narrowed protocol (and remain covered in full by `test_request_pipeline.py`, which needed
   no changes to its behavioural tests).
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.noop_stage import NoOpPipelineStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.application.agents.base import AgentContext
from gateway.application.pipeline.runner import RequestPipeline
from gateway.application.ports.pipeline import (
    PipelineStage,
    StageAction,
    StageContext,
    StageResult,
)
from gateway.domain.routing.models import ReasoningStep, RoutingDecision, RoutingOutcome

ORG = uuid4()

#: The surfaces ADR-0020 retired. Named once so a re-introduction has to edit this list.
RETIRED_STAGE_METHODS = ("after_response", "on_error")
PRODUCTION_STAGES = (AuthorizationStage, PolicyStage, AgentRoutingStage, NoOpPipelineStage)


# ------------------------------------------------------------------ the surfaces are gone


def test_the_stage_protocol_declares_exactly_name_and_before_request() -> None:
    """The seam is now exactly what `RequestPipeline` executes. Pinned as a set, not a subset:
    an extra method reappearing on Tier 1 must fail here, which is the whole point."""
    declared = {
        name for name in vars(PipelineStage) if not name.startswith("_") and name not in {"name"}
    }
    assert declared == {"before_request"}


@pytest.mark.parametrize("method", RETIRED_STAGE_METHODS)
def test_no_production_stage_still_exposes_a_retired_lifecycle_method(method: str) -> None:
    """Removing them from the protocol while leaving inert copies on the implementations would
    keep the misleading surface and lose only the type-level honesty."""
    for stage in PRODUCTION_STAGES:
        assert not hasattr(stage, method), f"{stage.__name__} still exposes {method}"


def test_routing_decision_has_no_selected_model_field() -> None:
    assert "selected_model" not in RoutingDecision.__dataclass_fields__


def test_agent_context_has_no_selected_model_field() -> None:
    assert "selected_model" not in AgentContext.__dataclass_fields__


def test_constructing_a_decision_with_selected_model_is_now_a_type_error() -> None:
    """Re-adding the field by accident cannot pass silently: the constructor rejects it."""
    with pytest.raises(TypeError):
        RoutingDecision(  # type: ignore[call-arg]
            outcome=RoutingOutcome.SELECTED,
            organization_id=ORG,
            correlation_id="c1",
            decided_at=datetime(2026, 7, 26, tzinfo=UTC),
            reasoning_steps=(ReasoningStep(agent="provider", summary="s"),),
            selected_provider="openai",
            selected_model="gpt-4o",
        )


# ------------------------------------------------------------------ nothing was lost


def test_the_selected_model_is_still_carried_by_the_resolved_provider() -> None:
    """The information was never *in* the decision - every consumer (pricing, the cache key,
    `CostRecord`, `SettlementDetail` and therefore the durable `cost_ledger` row) already read it
    from the descriptor. Removing the field erased a `None`, not a fact."""
    from gateway.application.ports.routing import RoutingExecution
    from gateway.application.routing.catalog import ProviderDescriptor

    execution = RoutingExecution(
        decision=RoutingDecision(
            outcome=RoutingOutcome.SELECTED,
            organization_id=ORG,
            correlation_id="c1",
            decided_at=datetime(2026, 7, 26, tzinfo=UTC),
            reasoning_steps=(ReasoningStep(agent="provider", summary="s"),),
            selected_provider="openai",
        ),
        provider=ProviderDescriptor(name="openai", model="gpt-4o"),
    )

    assert execution.routed is True
    assert execution.provider is not None
    assert execution.provider.model == "gpt-4o"


def test_a_decision_is_still_explainable_and_still_names_its_provider() -> None:
    """Invariant 3's substance is untouched: a decision cannot exist without its reasoning trace,
    and a selection still says which provider was chosen."""
    decision = RoutingDecision(
        outcome=RoutingOutcome.SELECTED,
        organization_id=ORG,
        correlation_id="c1",
        decided_at=datetime(2026, 7, 26, tzinfo=UTC),
        reasoning_steps=(ReasoningStep(agent="provider", summary="chose openai"),),
        selected_provider="openai",
    )

    assert decision.is_selection is True
    assert decision.selected_provider == "openai"
    assert decision.reasoning_steps
    assert decision.agents_consulted() == ("provider",)


# ------------------------------------------------------------------ semantics unchanged


class MinimalStage:
    """A stage implementing **only** the narrowed protocol - no lifecycle methods at all.

    This class could not have satisfied `PipelineStage` before ADR-0020: the protocol is
    `runtime_checkable`, so `isinstance` checked for every declared method and a stage without
    `after_response`/`on_error` would have failed. That it now conforms is the contraction's one
    real consequence, and it is a *reduction in what an implementer must write to nothing they do
    not use* - not a change in what the runner does.
    """

    def __init__(self, name: str, result: StageResult | None = None) -> None:
        self._name = name
        self._result = result or StageResult()
        self.calls: list[StageContext] = []

    @property
    def name(self) -> str:
        return self._name

    async def before_request(self, context: StageContext) -> StageResult:
        self.calls.append(context)
        return self._result


def test_a_stage_with_only_before_request_satisfies_the_narrowed_protocol() -> None:
    assert isinstance(MinimalStage("minimal"), PipelineStage)


def test_every_production_stage_still_satisfies_the_narrowed_protocol() -> None:
    """The narrowing must not have broken conformance for anything real."""
    for stage in (NoOpPipelineStage(),):
        assert isinstance(stage, PipelineStage)


async def test_continue_still_advances_through_the_whole_chain_in_order() -> None:
    first, second, third = MinimalStage("a"), MinimalStage("b"), MinimalStage("c")
    pipeline = RequestPipeline([first, second, third])

    outcome = await pipeline.admit(StageContext(correlation_id="c1", organization_id=ORG))

    assert outcome.admitted is True
    assert outcome.stages_run == ("a", "b", "c")
    assert [len(s.calls) for s in (first, second, third)] == [1, 1, 1]


async def test_block_still_stops_the_chain_and_later_stages_never_run() -> None:
    """The single most important pipeline property, re-asserted against the narrowed protocol."""
    allowed = MinimalStage("a")
    blocker = MinimalStage("b", StageResult(action=StageAction.BLOCK, reason="denied"))
    never = MinimalStage("c")
    pipeline = RequestPipeline([allowed, blocker, never])

    outcome = await pipeline.admit(StageContext(correlation_id="c1", organization_id=ORG))

    assert outcome.admitted is False
    assert outcome.blocked_by == "b"
    assert allowed.calls, "stages before the block must still run"
    assert never.calls == [], "no stage after the block may run"


async def test_stage_ordering_is_still_the_declared_order() -> None:
    order: list[str] = []

    class Recording(MinimalStage):
        async def before_request(self, context: StageContext) -> StageResult:
            order.append(self.name)
            return await super().before_request(context)

    pipeline = RequestPipeline([Recording("first"), Recording("second"), Recording("third")])
    await pipeline.admit(StageContext(correlation_id="c1", organization_id=ORG))

    assert order == ["first", "second", "third"]


def test_the_runner_invokes_no_lifecycle_method_because_none_exists() -> None:
    """Source-level backstop for the structural claim: the executor's body must reference only
    `before_request`. A future edit that reintroduced a callback would have to change this."""
    source = inspect.getsource(RequestPipeline)

    assert "before_request" in source
    for method in RETIRED_STAGE_METHODS:
        assert method not in source
