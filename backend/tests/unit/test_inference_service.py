"""InferenceService - the first end-to-end request path (ADR-0016 Slice 15).

Every collaborator here is the real one. Spies wrap rather than replace, because "the provider was
not called" and "budget was not reserved" are only meaningful if the things that did not happen are
the components that would really have done them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from gateway.adapters.authorization.in_memory_resolver import InMemoryPermissionResolver
from gateway.adapters.authorization.null_resolver import NullPermissionResolver
from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.noop_stage import NoOpPipelineStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.fake_client import FakeProviderClient
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.authorization.requirements import declare
from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.runner import EvaluationReport, EvaluationRunner
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import (
    ExecutionOutcome,
    InferenceCoordinator,
)
from gateway.application.pipeline.runner import AdmissionOutcome, RequestPipeline, StageRecord
from gateway.application.ports.evaluation import EvaluationInput
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.money import Money
from gateway.application.ports.pipeline import StageAction, StageContext
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
    ProviderUsage,
)
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.routing.catalog import InMemoryProviderCatalog, ProviderDescriptor
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.application.serving.inference_service import (
    InferenceService,
    RoutingTransportError,
    ServedInference,
)

ORG = uuid4()
PRINCIPAL = uuid4()
PERMISSION = "chat:invoke"
PROVIDER = ProviderDescriptor(name="openai", model="gpt-4o")
PRICE = ModelPrice(
    provider="openai",
    model="gpt-4o",
    input_price_per_1k=Decimal("1"),
    output_price_per_1k=Decimal("2"),
    currency="USD",
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


class NoSleep:
    """Retry backoff without the wall-clock wait."""

    def __init__(self) -> None:
        self.slept: list[timedelta] = []

    async def sleep(self, duration: timedelta) -> None:
        self.slept.append(duration)


# --- spies that wrap the real collaborators ----------------------------------------------------


class SpyProviderClient:
    def __init__(self, inner: FakeProviderClient) -> None:
        self._inner = inner
        self.invocations: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.invocations)

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        self.invocations.append(request.correlation_id)
        return await self._inner.invoke(provider, request)


class SpyLedger:
    """Counts every budget movement without changing any of them."""

    def __init__(self, inner: BudgetLedgerPort) -> None:
        self._inner = inner
        self.reserved: list[str] = []
        self.settled: list[str] = []
        self.released: list[str] = []

    @property
    def touched(self) -> bool:
        return bool(self.reserved or self.settled or self.released)

    async def reserve(self, organization_id: UUID, correlation_id: str, cost: Money) -> Any:
        self.reserved.append(correlation_id)
        return await self._inner.reserve(organization_id, correlation_id, cost)

    async def settle(self, organization_id: UUID, correlation_id: str, detail: Any) -> None:
        self.settled.append(correlation_id)
        await self._inner.settle(organization_id, correlation_id, detail)

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        self.released.append(correlation_id)
        await self._inner.release(organization_id, correlation_id)


class SpyEvaluationRunner(EvaluationRunner):
    def __init__(self) -> None:
        super().__init__([ResponseCompletenessEvaluator(), UsageAccountingConsistencyEvaluator()])
        self.runs: list[EvaluationInput] = []

    async def run(self, target: EvaluationInput) -> EvaluationReport:
        self.runs.append(target)
        return await super().run(target)


class Harness:
    """The whole request path, wired the way the container wires it."""

    def __init__(
        self,
        *,
        responses: list[ProviderResponse] | None = None,
        grant: bool = True,
        max_request_bytes: int = 128 * 1024,
        limit: Money | None = None,
        candidates: list[ProviderDescriptor] | None = None,
        max_attempts: int = 3,
    ) -> None:
        clock = FixedClock()
        self.client = SpyProviderClient(
            FakeProviderClient(
                sequence=responses
                or [ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())]
            )
        )
        self.ledger = SpyLedger(InMemoryBudgetLedger({ORG: limit or _budget()}))
        pricing = StaticPriceTable([PRICE])
        reservation = ReservationService(self.ledger, pricing, CostAccountant(pricing))
        self.coordinator = InferenceCoordinator(
            InMemoryResponseCache(clock),
            RequestDeduplicator(),
            reservation,
            ProviderExecutor(self.client),
        )
        self.sleeper = NoSleep()
        self.executor = ReflectiveExecutor(
            self.coordinator, RetryPolicy(max_attempts=max_attempts), self.sleeper
        )

        runtime = AgentRuntime(
            [PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()], clock
        )
        catalog = InMemoryProviderCatalog(
            {ORG: candidates if candidates is not None else [PROVIDER]}
        )
        resolver: InMemoryPermissionResolver | NullPermissionResolver
        if grant:
            resolver = InMemoryPermissionResolver({"caller": [PERMISSION]})
            resolver.assign(ORG, PRINCIPAL, ["caller"])
        else:
            resolver = NullPermissionResolver()

        self.evaluation = SpyEvaluationRunner()
        self.pipeline = RequestPipeline(
            [
                AuthorizationStage(resolver),
                PolicyStage(LocalPolicyEngine(max_request_bytes=max_request_bytes)),
                AgentRoutingStage(AgentOrchestratedRoutingEngine(catalog, runtime)),
            ]
        )
        self.service = InferenceService(self.pipeline, self.executor, self.evaluation)

    async def serve(self, payload: dict[str, Any] | None = None) -> ServedInference:
        body = payload if payload is not None else {"prompt": "hello"}
        context = StageContext(
            correlation_id="corr-1",
            organization_id=ORG,
            principal_id=PRINCIPAL,
            attributes={**declare(PERMISSION, resource="POST /v1/inference"), "request": body},
        )
        return await self.service.serve(
            context, InferenceRequest(correlation_id="corr-1", payload=body)
        )


def _usage() -> ProviderUsage:
    return ProviderUsage(prompt_tokens=10, completion_tokens=5)


def _budget() -> Money:
    return Money(Decimal("100.00"), "USD")


# --- the happy path ----------------------------------------------------------------------------


async def test_an_admitted_request_is_routed_executed_settled_and_evaluated() -> None:
    harness = Harness(limit=_budget())

    served = await harness.serve()

    assert served.admitted is True
    assert served.admission.stages_run == ("authorization", "policy", "agent_routing")
    assert served.reflection is not None
    assert served.reflection.final.outcome is ExecutionOutcome.EXECUTED
    assert served.reflection.final.response.ok is True
    assert served.reflection.final.cost is not None
    assert harness.client.invocations == ["corr-1#1"]
    assert harness.ledger.reserved == ["corr-1#1"]
    assert harness.ledger.settled == ["corr-1#1"]
    assert harness.ledger.released == []


async def test_evaluation_runs_exactly_once_on_the_final_result() -> None:
    harness = Harness(limit=_budget())

    served = await harness.serve()

    assert len(harness.evaluation.runs) == 1
    assert served.evaluation is not None
    assert served.evaluation.target_failed is False
    assert served.evaluation.evaluation_degraded is False
    assert harness.evaluation.runs[0].correlation_id == "corr-1"
    assert harness.evaluation.runs[0].outcome is ExecutionOutcome.EXECUTED


# --- refusal prevents every downstream side effect ---------------------------------------------


async def test_an_authorization_denial_reaches_nothing_downstream() -> None:
    """The property this slice exists to establish, asserted against every downstream owner."""
    harness = Harness(grant=False, limit=_budget())

    served = await harness.serve()

    assert served.admitted is False
    assert served.admission.blocked_by == "authorization"
    assert served.reflection is None
    assert served.evaluation is None
    assert harness.client.called is False
    assert harness.ledger.touched is False
    assert harness.evaluation.runs == []


async def test_a_policy_denial_reaches_nothing_downstream() -> None:
    harness = Harness(max_request_bytes=4, limit=_budget())

    served = await harness.serve({"prompt": "a payload that exceeds the configured limit"})

    assert served.admitted is False
    assert served.admission.blocked_by == "policy"
    assert served.reflection is None
    assert served.evaluation is None
    assert harness.client.called is False
    assert harness.ledger.touched is False


async def test_a_refusal_stops_before_routing_so_no_routing_decision_is_produced() -> None:
    harness = Harness(grant=False, limit=_budget())

    served = await harness.serve()

    assert "agent_routing" not in served.admission.stages_run


async def test_a_refusal_is_not_reported_as_a_provider_failure() -> None:
    """Synthesizing ProviderResponse(ok=False) would make a denial and an outage the same fact."""
    harness = Harness(grant=False, limit=_budget())

    served = await harness.serve()

    assert served.reflection is None
    assert served.refusal_reason is not None
    assert "provider" not in served.refusal_reason.lower()


# --- budget, provider failure, cache -----------------------------------------------------------


async def test_a_budget_denial_means_the_provider_is_never_called() -> None:
    harness = Harness(limit=Money(Decimal("0.00000001"), "USD"))

    served = await harness.serve()

    assert served.admitted is True
    assert served.reflection is not None
    assert served.reflection.final.outcome is ExecutionOutcome.BUDGET_DENIED
    assert harness.client.called is False
    assert harness.ledger.reserved  # the gate ran...
    assert harness.ledger.settled == []  # ...and nothing was spent
    assert len(harness.evaluation.runs) == 1


async def test_a_provider_failure_releases_the_reservation_and_settles_nothing() -> None:
    failure = ProviderResponse(
        ok=False, error="upstream 500", error_category=ProviderErrorCategory.INVALID_REQUEST
    )
    harness = Harness(responses=[failure], limit=_budget(), max_attempts=1)

    served = await harness.serve()

    assert served.reflection is not None
    assert served.reflection.final.response.ok is False
    assert harness.ledger.reserved == ["corr-1#1"]
    assert harness.ledger.released == ["corr-1#1"]
    assert harness.ledger.settled == []


async def test_a_cache_hit_calls_no_provider_and_accounts_no_second_time() -> None:
    harness = Harness(
        responses=[ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())],
        limit=_budget(),
    )

    first = await harness.serve()
    assert first.reflection is not None
    assert first.reflection.final.outcome is ExecutionOutcome.EXECUTED

    second = await harness.serve()

    assert second.reflection is not None
    assert second.reflection.final.outcome is ExecutionOutcome.CACHE_HIT
    # The provider was called once in total, and only for the miss.
    assert harness.client.invocations == ["corr-1#1"]
    # A hit spends nothing, so it neither reserves nor settles a second time.
    assert harness.ledger.reserved == ["corr-1#1"]
    assert harness.ledger.settled == ["corr-1#1"]
    assert second.reflection.final.response.usage is None
    assert second.reflection.final.cost is None


async def test_a_cache_hit_is_still_evaluated_exactly_once() -> None:
    harness = Harness(limit=_budget())
    await harness.serve()
    harness.evaluation.runs.clear()

    served = await harness.serve()

    assert len(harness.evaluation.runs) == 1
    assert served.evaluation is not None
    assert served.evaluation.target_failed is False


# --- reflection stays behind its own boundary ---------------------------------------------------


async def test_retries_go_through_the_coordinator_and_are_evaluated_only_once_at_the_end() -> None:
    transient = ProviderResponse(
        ok=False, error="rate limited", error_category=ProviderErrorCategory.RATE_LIMITED
    )
    success = ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())
    harness = Harness(responses=[transient, success], limit=_budget())

    served = await harness.serve()

    assert served.reflection is not None
    assert served.reflection.attempt_count == 2
    assert served.reflection.succeeded is True
    # Each attempt reserved under its own identity, so neither collided with the other.
    assert harness.client.invocations == ["corr-1#1", "corr-1#2"]
    assert harness.ledger.reserved == ["corr-1#1", "corr-1#2"]
    assert harness.ledger.released == ["corr-1#1"]
    assert harness.ledger.settled == ["corr-1#2"]
    # ...and the whole request is one evaluation, of the final result.
    assert len(harness.evaluation.runs) == 1
    assert harness.evaluation.runs[0].outcome is ExecutionOutcome.EXECUTED
    assert harness.evaluation.runs[0].response.ok is True


async def test_a_transient_failure_a_retry_recovered_is_not_reported_as_a_quality_problem() -> None:
    transient = ProviderResponse(
        ok=False, error="timeout", error_category=ProviderErrorCategory.TIMEOUT
    )
    success = ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())
    harness = Harness(responses=[transient, success], limit=_budget())

    served = await harness.serve()

    assert served.evaluation is not None
    assert served.evaluation.target_failed is False


# --- routing declined --------------------------------------------------------------------------


async def test_an_admitted_but_unroutable_request_calls_no_provider_and_is_still_evaluated() -> (
    None
):
    """Routing refusing is a decision the agents made and explained; the coordinator already owns
    that path, so the service passes it through rather than inventing a second interpretation."""
    harness = Harness(candidates=[], limit=_budget())

    served = await harness.serve()

    assert served.admitted is True
    assert served.reflection is not None
    assert served.reflection.final.outcome is ExecutionOutcome.NOT_ROUTED
    assert harness.client.called is False
    assert harness.ledger.touched is False
    assert len(harness.evaluation.runs) == 1


# --- composition invariants ---------------------------------------------------------------------


async def test_the_service_reads_routing_from_the_pipeline_rather_than_routing_again() -> None:
    """A second call to the engine would produce a second explanation of one request."""
    harness = Harness(limit=_budget())

    served = await harness.serve()

    assert served.reflection is not None
    transported = [
        record
        for record in served.admission.records
        if record.action is StageAction.ANNOTATE and record.stage == "agent_routing"
    ]
    assert len(transported) == 1
    assert served.reflection.execution is transported[0].annotations["routing_execution"]


async def test_an_admitted_request_with_no_transported_routing_is_a_defect_not_a_response() -> None:
    """A composition root that forgot the routing stage is a real misconfiguration, and it must
    surface as a defect rather than as a response - the same reasoning RoutingIntegrityError
    applies inside the engine. Driven through the public path, not the private helper."""
    harness = Harness(limit=_budget())
    harness.service = InferenceService(
        RequestPipeline([NoOpPipelineStage("authorization")]),
        harness.executor,
        harness.evaluation,
    )

    with pytest.raises(RoutingTransportError, match="no routing execution was transported"):
        await harness.serve()

    assert harness.client.called is False
    assert harness.ledger.touched is False


def test_an_admitted_request_must_record_an_execution() -> None:
    admitted = AdmissionOutcome(records=(StageRecord(stage="a", action=StageAction.CONTINUE),))
    with pytest.raises(ValueError, match="must record an execution result"):
        ServedInference(admission=admitted)


async def test_a_refused_request_cannot_carry_an_execution() -> None:
    """Built from a genuinely executed request, so the rejected combination is one the type
    system permits and only the invariant forbids."""
    harness = Harness(limit=_budget())
    executed = await harness.serve()
    assert executed.reflection is not None

    refused = AdmissionOutcome(
        records=(StageRecord(stage="a", action=StageAction.BLOCK, reason="no"),),
        blocked_by="a",
        reason="no",
    )
    with pytest.raises(ValueError, match="cannot have been executed"):
        ServedInference(admission=refused, reflection=executed.reflection)


async def test_a_refused_request_exposes_the_caller_visible_reason_only() -> None:
    harness = Harness(grant=False, limit=_budget())

    served = await harness.serve()

    assert served.refusal_reason == "principal lacks the required permissions"
    assert PERMISSION not in (served.refusal_reason or "")


async def test_tenant_identity_survives_the_whole_path_into_the_evaluation_record() -> None:
    harness = Harness(limit=_budget())

    await harness.serve()

    assert harness.evaluation.runs[0].organization_id == ORG
