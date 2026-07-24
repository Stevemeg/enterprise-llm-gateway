"""RequestPipeline - the executor for the Tier-1 stage seam (ADR-0016 invariant 5, Slice 14).

The tests that matter most here are the negative ones. Until this slice every stage was
constructed-and-never-run, so "authorization denies" was a property of a class nobody called. What
these prove is the composed behaviour: a refused request does not reach the next control, and in
particular does not reach the routing engine.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from gateway.adapters.authorization.in_memory_resolver import InMemoryPermissionResolver
from gateway.adapters.authorization.null_resolver import NullPermissionResolver
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.noop_stage import NoOpPipelineStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.authorization.requirements import declare
from gateway.application.pipeline.runner import (
    GENERIC_BLOCK_REASON,
    AdmissionOutcome,
    RequestPipeline,
    StageRecord,
)
from gateway.application.ports.pipeline import StageAction, StageContext, StageResult
from gateway.application.ports.policy import (
    PolicyEngineUnavailableError,
    PolicyQuery,
    PolicyVerdict,
)
from gateway.application.ports.routing import ROUTING_EXECUTION_KEY, RoutingExecution
from gateway.application.routing.catalog import InMemoryProviderCatalog, ProviderDescriptor
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.domain.routing.models import RoutingDecision

ORG = uuid4()
PRINCIPAL = uuid4()
PERMISSION = "chat:invoke"


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


# --- test doubles -----------------------------------------------------------------------------


class RecordingStage:
    """A stage that records every call and returns a scripted result."""

    def __init__(self, name: str, result: StageResult | None = None) -> None:
        self._name = name
        self._result = result or StageResult()
        self.calls: list[StageContext] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def called(self) -> bool:
        return bool(self.calls)

    def rename(self, name: str) -> None:
        self._name = name

    async def before_request(self, context: StageContext) -> StageResult:
        self.calls.append(context)
        return self._result

    async def after_response(self, context: StageContext) -> StageResult:
        return StageResult()

    async def on_error(self, context: StageContext, error: Exception) -> StageResult:
        return StageResult()


class ExplodingStage(RecordingStage):
    async def before_request(self, context: StageContext) -> StageResult:
        self.calls.append(context)
        raise RuntimeError("stage is broken")


class MalformedStage(RecordingStage):
    async def before_request(self, context: StageContext) -> Any:
        self.calls.append(context)
        return "admitted"  # not a StageResult at all


class MutatingStage(RecordingStage):
    """Writes into the attributes bag it was handed, to prove a later stage cannot see it."""

    async def before_request(self, context: StageContext) -> StageResult:
        self.calls.append(context)
        context.attributes["injected"] = "by an earlier stage"
        return StageResult(action=StageAction.ANNOTATE, annotations={"annotated": True})


class SpyRoutingEngine:
    """Wraps the real engine and counts invocations.

    Wrapping rather than faking is deliberate: "routing did not happen" is only meaningful
    evidence if the thing that did not happen is the real routing engine.
    """

    def __init__(self, inner: AgentOrchestratedRoutingEngine) -> None:
        self._inner = inner
        self.calls: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.calls)

    async def route(
        self,
        *,
        organization_id: UUID,
        correlation_id: str,
        request: dict[str, Any] | None = None,
    ) -> RoutingExecution:
        self.calls.append(correlation_id)
        return await self._inner.route(
            organization_id=organization_id, correlation_id=correlation_id, request=request
        )


class SpyPolicyEngine:
    def __init__(self, inner: LocalPolicyEngine) -> None:
        self._inner = inner
        self.calls: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.calls)

    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        self.calls.append(query.correlation_id)
        return await self._inner.evaluate(query)


class UnavailablePolicyEngine:
    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        raise PolicyEngineUnavailableError("policy store unreachable")


# --- builders ---------------------------------------------------------------------------------


def _routing_engine() -> SpyRoutingEngine:
    runtime = AgentRuntime(
        [PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()], FixedClock()
    )
    catalog = InMemoryProviderCatalog({ORG: [ProviderDescriptor(name="openai", model="gpt-4o")]})
    return SpyRoutingEngine(AgentOrchestratedRoutingEngine(catalog, runtime))


def _granting_resolver() -> InMemoryPermissionResolver:
    resolver = InMemoryPermissionResolver({"caller": [PERMISSION]})
    resolver.assign(ORG, PRINCIPAL, ["caller"])
    return resolver


def _context(**attributes: Any) -> StageContext:
    merged: dict[str, Any] = {**declare(PERMISSION, resource="POST /v1/inference")}
    merged.update(attributes)
    return StageContext(
        correlation_id="corr-1",
        organization_id=ORG,
        principal_id=PRINCIPAL,
        attributes=merged,
    )


# --- registration and ordering ----------------------------------------------------------------


def test_an_empty_pipeline_is_refused_at_construction() -> None:
    """A pipeline with no stages admits everything while looking configured."""
    with pytest.raises(ValueError, match="at least one stage"):
        RequestPipeline([])


def test_duplicate_stage_names_are_refused_at_construction() -> None:
    """Two stages under one name make 'blocked by policy' stop identifying which control refused."""
    with pytest.raises(ValueError, match="unique"):
        RequestPipeline([NoOpPipelineStage("policy"), NoOpPipelineStage("policy")])


def test_the_registered_chain_reports_its_execution_order() -> None:
    pipeline = RequestPipeline([NoOpPipelineStage("a"), NoOpPipelineStage("b")])
    assert pipeline.stage_names == ("a", "b")


def test_a_name_that_changes_after_registration_does_not_change_the_audit_trail() -> None:
    stage = RecordingStage("original")
    pipeline = RequestPipeline([stage])
    stage.rename("renamed")

    assert pipeline.stage_names == ("original",)
    assert stage.name == "renamed"


async def test_stages_run_in_declared_order() -> None:
    order: list[str] = []

    class Ordered(RecordingStage):
        async def before_request(self, context: StageContext) -> StageResult:
            order.append(self.name)
            return StageResult()

    pipeline = RequestPipeline([Ordered("first"), Ordered("second"), Ordered("third")])
    outcome = await pipeline.admit(_context())

    assert order == ["first", "second", "third"]
    assert outcome.stages_run == ("first", "second", "third")


# --- admission and refusal --------------------------------------------------------------------


async def test_a_chain_that_all_continues_admits_the_request() -> None:
    outcome = await RequestPipeline([NoOpPipelineStage("a"), NoOpPipelineStage("b")]).admit(
        _context()
    )

    assert outcome.admitted is True
    assert outcome.blocked_by is None
    assert outcome.reason is None
    assert [record.action for record in outcome.records] == [StageAction.CONTINUE] * 2


async def test_the_first_block_stops_the_chain_and_later_stages_never_run() -> None:
    """The central property of the slice: a refused request does not reach the next control."""
    blocker = RecordingStage("blocker", StageResult(action=StageAction.BLOCK, reason="denied"))
    downstream = RecordingStage("downstream")

    outcome = await RequestPipeline([blocker, downstream]).admit(_context())

    assert outcome.admitted is False
    assert outcome.blocked_by == "blocker"
    assert outcome.reason == "denied"
    assert blocker.called is True
    assert downstream.called is False
    assert outcome.stages_run == ("blocker",)


async def test_a_block_midway_runs_earlier_stages_but_no_later_ones() -> None:
    first = RecordingStage("first")
    blocker = RecordingStage("blocker", StageResult(action=StageAction.BLOCK, reason="denied"))
    last = RecordingStage("last")

    outcome = await RequestPipeline([first, blocker, last]).admit(_context())

    assert outcome.stages_run == ("first", "blocker")
    assert first.called is True
    assert last.called is False


async def test_annotate_does_not_block_and_is_preserved_in_the_record() -> None:
    stage = RecordingStage(
        "annotator", StageResult(action=StageAction.ANNOTATE, annotations={"seen": True})
    )
    outcome = await RequestPipeline([stage, NoOpPipelineStage("after")]).admit(_context())

    assert outcome.admitted is True
    assert outcome.records[0].action is StageAction.ANNOTATE
    assert outcome.records[0].annotations == {"seen": True}


async def test_each_stage_keeps_its_own_annotations_so_common_keys_do_not_collide() -> None:
    """Both RBAC and policy emit a 'stage' key; a merged bag would lose one control's audit."""
    a = RecordingStage("a", StageResult(annotations={"stage": "a", "rule": "one"}))
    b = RecordingStage("b", StageResult(annotations={"stage": "b", "rule": "two"}))

    outcome = await RequestPipeline([a, b]).admit(_context())

    assert outcome.records[0].annotations == {"stage": "a", "rule": "one"}
    assert outcome.records[1].annotations == {"stage": "b", "rule": "two"}


# --- fail closed ------------------------------------------------------------------------------


async def test_a_stage_that_raises_blocks_rather_than_propagating() -> None:
    """A crashed control has not admitted anything, and must not become a 500 in place of a
    decision."""
    exploding = ExplodingStage("exploding")
    downstream = RecordingStage("downstream")

    outcome = await RequestPipeline([exploding, downstream]).admit(_context())

    assert outcome.admitted is False
    assert outcome.blocked_by == "exploding"
    assert outcome.reason == GENERIC_BLOCK_REASON
    assert outcome.records[0].annotations["stage_error"] is True
    assert "RuntimeError: stage is broken" in outcome.records[0].annotations["detail"]
    assert downstream.called is False


async def test_a_stage_returning_the_wrong_type_blocks_rather_than_being_treated_as_allow() -> None:
    """PipelineStage is structurally checked, so a stage can return something else entirely."""
    outcome = await RequestPipeline([MalformedStage("malformed")]).admit(_context())

    assert outcome.admitted is False
    assert outcome.records[0].annotations["malformed_result"] is True
    assert "str" in outcome.records[0].annotations["detail"]


async def test_an_unexplained_block_is_still_a_block() -> None:
    """StageResult documents that BLOCK carries a reason but does not enforce it; the runner
    substitutes a generic reason rather than letting an unexplainable denial become admission."""
    stage = RecordingStage("silent", StageResult(action=StageAction.BLOCK, reason=None))

    outcome = await RequestPipeline([stage]).admit(_context())

    assert outcome.admitted is False
    assert outcome.reason == GENERIC_BLOCK_REASON
    assert outcome.records[0].annotations["unexplained_block"] is True


async def test_a_runner_generated_block_reason_names_no_stage_rule_or_threshold() -> None:
    outcome = await RequestPipeline([ExplodingStage("exploding")]).admit(_context())

    assert outcome.reason is not None
    assert "exploding" not in outcome.reason
    assert "RuntimeError" not in outcome.reason


# --- stage isolation --------------------------------------------------------------------------


async def test_a_stage_cannot_alter_what_a_later_stage_sees() -> None:
    mutator = MutatingStage("mutator")
    observer = RecordingStage("observer")

    await RequestPipeline([mutator, observer]).admit(_context())

    assert "injected" not in observer.calls[0].attributes


async def test_one_stage_s_annotations_do_not_become_another_stage_s_input() -> None:
    annotator = RecordingStage("annotator", StageResult(annotations={"policy_allowed": True}))
    observer = RecordingStage("observer")

    await RequestPipeline([annotator, observer]).admit(_context())

    assert "policy_allowed" not in observer.calls[0].attributes


async def test_the_caller_s_context_is_not_mutated_by_the_pipeline() -> None:
    context = _context()
    original = dict(context.attributes)

    await RequestPipeline([MutatingStage("mutator")]).admit(context)

    assert context.attributes == original


async def test_stages_still_receive_the_caller_s_own_attributes() -> None:
    """Copying the bag must not mean emptying it - the request's declaration has to arrive."""
    observer = RecordingStage("observer")

    await RequestPipeline([observer]).admit(_context(extra="value"))

    assert observer.calls[0].attributes["extra"] == "value"
    assert observer.calls[0].organization_id == ORG
    assert observer.calls[0].principal_id == PRINCIPAL
    assert observer.calls[0].correlation_id == "corr-1"


# --- outcome invariants -----------------------------------------------------------------------


def test_an_outcome_must_record_at_least_one_stage() -> None:
    with pytest.raises(ValueError, match="at least one stage"):
        AdmissionOutcome(records=())


def test_a_block_must_name_a_reason() -> None:
    record = StageRecord(stage="s", action=StageAction.BLOCK, reason="x")
    with pytest.raises(ValueError, match="without a reason"):
        AdmissionOutcome(records=(record,), blocked_by="s")


def test_an_admitted_request_cannot_carry_a_block_reason() -> None:
    record = StageRecord(stage="s", action=StageAction.CONTINUE)
    with pytest.raises(ValueError, match="cannot carry a block reason"):
        AdmissionOutcome(records=(record,), reason="denied")


def test_stage_record_reports_whether_it_blocked() -> None:
    assert StageRecord(stage="s", action=StageAction.BLOCK, reason="x").blocked is True
    assert StageRecord(stage="s", action=StageAction.CONTINUE).blocked is False


# --- the composed admission chain (the debt this slice closes) --------------------------------


def _real_pipeline(
    *,
    resolver: InMemoryPermissionResolver | NullPermissionResolver | None = None,
    policy_engine: Any = None,
    routing: SpyRoutingEngine | None = None,
) -> tuple[RequestPipeline, SpyRoutingEngine, Any]:
    engine = routing or _routing_engine()
    policy = policy_engine or SpyPolicyEngine(LocalPolicyEngine())
    pipeline = RequestPipeline(
        [
            AuthorizationStage(resolver or _granting_resolver()),
            PolicyStage(policy),
            AgentRoutingStage(engine),
        ]
    )
    return pipeline, engine, policy


async def test_an_authorized_and_permitted_request_reaches_routing() -> None:
    pipeline, routing, policy = _real_pipeline()

    outcome = await pipeline.admit(_context(request={"prompt": "hello"}))

    assert outcome.admitted is True
    assert routing.called is True
    assert policy.called is True
    execution = outcome.records[-1].annotations[ROUTING_EXECUTION_KEY]
    assert isinstance(execution.decision, RoutingDecision)
    assert execution.decision.selected_provider == "openai"
    assert execution.provider is not None


async def test_an_authorization_denial_means_no_policy_evaluation_and_no_routing() -> None:
    """Slices 5-13 could not prove this: nothing executed the stages, so a denial prevented
    nothing. This is the assertion that makes the admission chain real."""
    pipeline, routing, policy = _real_pipeline(resolver=NullPermissionResolver())

    outcome = await pipeline.admit(_context(request={"prompt": "hello"}))

    assert outcome.admitted is False
    assert outcome.blocked_by == "authorization"
    assert routing.called is False
    assert policy.called is False


async def test_an_undeclared_request_is_denied_before_routing() -> None:
    pipeline, routing, _ = _real_pipeline()
    context = StageContext(correlation_id="corr-1", organization_id=ORG, principal_id=PRINCIPAL)

    outcome = await pipeline.admit(context)

    assert outcome.blocked_by == "authorization"
    assert outcome.records[0].annotations["undeclared"] is True
    assert routing.called is False


async def test_an_unauthenticated_request_is_denied_before_routing() -> None:
    pipeline, routing, _ = _real_pipeline()
    context = StageContext(
        correlation_id="corr-1", organization_id=ORG, attributes=declare(PERMISSION)
    )

    outcome = await pipeline.admit(context)

    assert outcome.blocked_by == "authorization"
    assert routing.called is False


async def test_a_policy_denial_means_no_routing() -> None:
    pipeline, routing, _ = _real_pipeline(
        policy_engine=SpyPolicyEngine(LocalPolicyEngine(max_request_bytes=8))
    )

    outcome = await pipeline.admit(_context(request={"prompt": "a payload beyond the limit"}))

    assert outcome.admitted is False
    assert outcome.blocked_by == "policy"
    assert routing.called is False


async def test_a_policy_engine_outage_means_no_routing() -> None:
    """ADR-0009 row 1 applied to the composed path: losing policy must cost enforcement nothing."""
    pipeline, routing, _ = _real_pipeline(policy_engine=UnavailablePolicyEngine())

    outcome = await pipeline.admit(_context(request={"prompt": "hello"}))

    assert outcome.admitted is False
    assert outcome.blocked_by == "policy"
    assert outcome.records[1].annotations["policy_unavailable"] is True
    assert routing.called is False


async def test_a_denial_reason_does_not_disclose_the_missing_permission() -> None:
    pipeline, _, _ = _real_pipeline(resolver=NullPermissionResolver())

    outcome = await pipeline.admit(_context(request={"prompt": "hello"}))

    assert outcome.reason is not None
    assert PERMISSION not in outcome.reason
    # ...while the audit trail still records exactly what was missing.
    assert outcome.records[0].annotations["missing_permissions"] == (PERMISSION,)


# --- tenancy, concurrency, idempotency ---------------------------------------------------------


async def test_a_grant_in_one_tenant_does_not_admit_a_request_in_another() -> None:
    other_org = uuid4()
    pipeline, routing, _ = _real_pipeline()
    context = StageContext(
        correlation_id="corr-1",
        organization_id=other_org,
        principal_id=PRINCIPAL,
        attributes=declare(PERMISSION),
    )

    outcome = await pipeline.admit(context)

    assert outcome.admitted is False
    assert outcome.blocked_by == "authorization"
    assert routing.called is False


async def test_concurrent_admissions_do_not_interleave_their_records() -> None:
    """The pipeline holds no per-request state, so two callers cannot observe each other.

    The suspension point is inside the stage, so the two admissions genuinely interleave: without
    per-call record accumulation the second request's verdicts would land in the first's outcome.
    """

    class Interleaving(RecordingStage):
        async def before_request(self, context: StageContext) -> StageResult:
            await asyncio.sleep(0)
            return StageResult(annotations={"correlation_id": context.correlation_id})

    pipeline = RequestPipeline([Interleaving("first"), Interleaving("second")])
    a, b = await asyncio.gather(
        pipeline.admit(StageContext(correlation_id="a", organization_id=ORG)),
        pipeline.admit(StageContext(correlation_id="b", organization_id=uuid4())),
    )

    assert [record.annotations["correlation_id"] for record in a.records] == ["a", "a"]
    assert [record.annotations["correlation_id"] for record in b.records] == ["b", "b"]


async def test_admitting_the_same_request_twice_yields_the_same_outcome() -> None:
    pipeline, _, _ = _real_pipeline(resolver=NullPermissionResolver())
    context = _context(request={"prompt": "hello"})

    first = await pipeline.admit(context)
    second = await pipeline.admit(context)

    assert first == second
