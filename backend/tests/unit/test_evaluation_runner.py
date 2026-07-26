"""EvaluationRunner tests (ADR-0016 Slice 12).

Covers the runner's own contract (ordering, error isolation, report semantics) and the
observation boundary: evaluation runs over a *completed* inference driven by the real Slice-10
coordinator and real Slice-9 reservation path, and is proven to change none of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.health.in_memory_circuit_breaker import InMemoryCircuitBreaker
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.fake_client import FakeProviderClient
from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.runner import EvaluationReport, EvaluationRunner
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import (
    InferenceCoordinator,
)
from gateway.application.ports.evaluation import (
    EvaluationInput,
    EvaluationOutcome,
    EvaluationResult,
)
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.ledger import ReservationOutcome
from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
    ProviderUsage,
)
from gateway.application.ports.routing import RoutingExecution
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.domain.routing.models import ReasoningStep, RoutingDecision, RoutingOutcome
from tests.support.accounting import reservation_service

ORG = uuid4()
OPENAI = ProviderDescriptor(name="openai", model="gpt-4o")
PRICE = ModelPrice(
    provider="openai",
    model="gpt-4o",
    input_price_per_1k=Decimal("1"),
    output_price_per_1k=Decimal("2"),
    currency="USD",
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


class RecordingSleeper:
    def __init__(self) -> None:
        self.slept: list[object] = []

    async def sleep(self, duration: object) -> None:
        self.slept.append(duration)


class ExplodingEvaluator:
    """An evaluator with a defect - it raises instead of returning a verdict."""

    def __init__(self, name: str = "exploding") -> None:
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, target: EvaluationInput) -> EvaluationResult:
        self.calls += 1
        raise RuntimeError("evaluator is broken")


class RecordingEvaluator:
    """Passes always; records the order in which it was invoked."""

    def __init__(self, name: str, log: list[str]) -> None:
        self._name = name
        self._log = log

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, target: EvaluationInput) -> EvaluationResult:
        self._log.append(self._name)
        return EvaluationResult(evaluator=self._name, outcome=EvaluationOutcome.PASSED)


def _decision(outcome: RoutingOutcome = RoutingOutcome.SELECTED) -> RoutingDecision:
    return RoutingDecision(
        outcome=outcome,
        organization_id=ORG,
        correlation_id="c1",
        decided_at=datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC),
        reasoning_steps=(ReasoningStep(agent="provider", summary="stub"),),
        selected_provider="openai" if outcome is RoutingOutcome.SELECTED else None,
    )


def _execution(outcome: RoutingOutcome = RoutingOutcome.SELECTED) -> RoutingExecution:
    return RoutingExecution(
        decision=_decision(outcome),
        provider=OPENAI if outcome is RoutingOutcome.SELECTED else None,
    )


def _request(correlation_id: str = "c1") -> InferenceRequest:
    return InferenceRequest(correlation_id=correlation_id, payload={"prompt": "hello"})


def _ok(text: str = "world") -> ProviderResponse:
    return ProviderResponse(
        ok=True,
        content={"text": text},
        provider="openai",
        usage=ProviderUsage(prompt_tokens=10, completion_tokens=5),
    )


def _input(outcome: ExecutionOutcome, response: ProviderResponse) -> EvaluationInput:
    return EvaluationInput(
        organization_id=ORG, correlation_id="c1", outcome=outcome, response=response
    )


def _production_runner() -> EvaluationRunner:
    return EvaluationRunner(
        (ResponseCompletenessEvaluator(), UsageAccountingConsistencyEvaluator())
    )


def _coordinator(
    client: FakeProviderClient, ledger: InMemoryBudgetLedger, cache: InMemoryResponseCache
) -> InferenceCoordinator:
    pricing = StaticPriceTable((PRICE,))
    return InferenceCoordinator(
        cache,
        RequestDeduplicator(),
        reservation_service(ledger, pricing),
        ProviderExecutor(client),
        InMemoryCircuitBreaker(FixedClock()),
    )


# ------------------------------------------------------------------ runner contract


async def test_runs_every_evaluator_in_declared_order() -> None:
    log: list[str] = []
    runner = EvaluationRunner((RecordingEvaluator("first", log), RecordingEvaluator("second", log)))

    report = await runner.run(_input(ExecutionOutcome.EXECUTED, _ok()))

    assert log == ["first", "second"], "ordering must be the declared order, deterministically"
    assert [r.evaluator for r in report.results] == ["first", "second"]


async def test_report_is_byte_identical_across_repeated_runs() -> None:
    runner = _production_runner()
    target = _input(ExecutionOutcome.EXECUTED, _ok())

    assert await runner.run(target) == await runner.run(target)


async def test_an_empty_evaluator_chain_is_rejected_at_construction() -> None:
    """An empty chain yields silence that looks like a clean bill of health."""
    with pytest.raises(ValueError, match="at least one evaluator"):
        EvaluationRunner(())


def test_a_report_must_carry_at_least_one_result() -> None:
    with pytest.raises(ValueError, match="at least one result"):
        EvaluationReport(organization_id=ORG, correlation_id="c1", results=())


async def test_report_preserves_tenant_and_request_identity() -> None:
    runner = _production_runner()

    report = await runner.run(_input(ExecutionOutcome.EXECUTED, _ok()))

    assert report.organization_id == ORG
    assert report.correlation_id == "c1"


# ------------------------------------------------------------------ error isolation


async def test_an_evaluator_that_raises_becomes_an_error_result_not_a_crash() -> None:
    runner = EvaluationRunner((ExplodingEvaluator(),))

    report = await runner.run(_input(ExecutionOutcome.EXECUTED, _ok()))

    assert len(report.results) == 1
    assert report.results[0].outcome is EvaluationOutcome.ERROR
    assert "RuntimeError" in report.results[0].detail
    assert report.evaluation_degraded is True


async def test_one_evaluator_erroring_does_not_erase_the_others() -> None:
    log: list[str] = []
    runner = EvaluationRunner(
        (
            RecordingEvaluator("before", log),
            ExplodingEvaluator(),
            RecordingEvaluator("after", log),
        )
    )

    report = await runner.run(_input(ExecutionOutcome.EXECUTED, _ok()))

    assert log == ["before", "after"], "the chain must continue past a broken evaluator"
    assert [r.outcome for r in report.results] == [
        EvaluationOutcome.PASSED,
        EvaluationOutcome.ERROR,
        EvaluationOutcome.PASSED,
    ]


async def test_evaluator_error_is_distinct_from_target_failure() -> None:
    """The distinction this capability exists to preserve: a broken evaluator and a bad response
    must never produce the same signal."""
    broken = EvaluationRunner((ExplodingEvaluator(),))
    bad_target = _production_runner()

    degraded = await broken.run(_input(ExecutionOutcome.EXECUTED, _ok()))
    failing = await bad_target.run(
        _input(
            ExecutionOutcome.EXECUTED,
            ProviderResponse(ok=True, content=None, provider="openai", usage=None),
        )
    )

    assert degraded.evaluation_degraded is True
    assert degraded.target_failed is False, "a broken evaluator says nothing about the inference"
    assert failing.target_failed is True
    assert failing.evaluation_degraded is False, "a bad response is not an evaluator fault"


# ------------------------------------------------------------------ observation boundary


async def test_evaluation_does_not_invoke_the_provider_or_touch_budget() -> None:
    """Evaluation observes a finished outcome; it must add no provider call and no budget effect."""
    client = FakeProviderClient(responses={"openai": _ok()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator = _coordinator(client, ledger, InMemoryResponseCache(FixedClock()))
    result = await coordinator.execute(_execution(), _request())
    calls_before = len(client.calls)

    await _production_runner().run(_input(result.outcome, result.response))

    assert len(client.calls) == calls_before, "evaluation must not reach a provider"
    # Budget is exactly where execution left it: settled once, no new reservation, no release.
    probe = await ledger.reserve(ORG, "probe", Money(Decimal("1000"), "USD"))
    assert probe.outcome is ReservationOutcome.EXCEEDED


async def test_evaluation_cannot_alter_the_response_the_caller_received() -> None:
    client = FakeProviderClient(responses={"openai": _ok()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator = _coordinator(client, ledger, InMemoryResponseCache(FixedClock()))
    result = await coordinator.execute(_execution(), _request())
    response_before = result.response

    await _production_runner().run(_input(result.outcome, result.response))

    assert result.response is response_before
    assert result.response == _ok()


async def test_evaluation_cannot_mutate_the_routing_decision() -> None:
    execution = _execution()
    decision_before = execution.decision
    client = FakeProviderClient(responses={"openai": _ok()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator = _coordinator(client, ledger, InMemoryResponseCache(FixedClock()))
    result = await coordinator.execute(execution, _request())

    await _production_runner().run(_input(result.outcome, result.response))

    assert execution.decision is decision_before
    assert execution.decision.outcome is RoutingOutcome.SELECTED
    assert execution.decision.correlation_id == "c1"
    with pytest.raises((AttributeError, TypeError)):
        execution.decision.outcome = RoutingOutcome.NO_CANDIDATE  # type: ignore[misc]


# ------------------------------------------------------------------ cache-hit semantics


async def test_a_cache_hit_is_evaluated_and_correctly_reports_no_usage() -> None:
    """The Slice-10 invariant, observed: a hit delivers content but must carry no usage."""
    client = FakeProviderClient(responses={"openai": _ok()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator = _coordinator(client, ledger, InMemoryResponseCache(FixedClock()))
    await coordinator.execute(_execution(), _request("first"))

    hit = await coordinator.execute(_execution(), _request("second"))
    assert hit.outcome is ExecutionOutcome.CACHE_HIT

    report = await _production_runner().run(_input(hit.outcome, hit.response))

    assert report.target_failed is False
    assert report.evaluation_degraded is False
    assert {r.outcome for r in report.results} == {EvaluationOutcome.PASSED}


# ------------------------------------------------------------------ reflection semantics


async def test_a_retried_inference_is_evaluated_once_on_its_final_outcome() -> None:
    """Evaluation is per-inference, not per-attempt: retries are reflection's concern, and the
    final outcome is the one that was delivered."""
    client = FakeProviderClient(
        sequence=[
            ProviderResponse(
                ok=False,
                error="rate limited",
                provider="openai",
                error_category=ProviderErrorCategory.RATE_LIMITED,
            ),
            _ok("recovered"),
        ]
    )
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator = _coordinator(client, ledger, InMemoryResponseCache(FixedClock()))
    reflective = ReflectiveExecutor(coordinator, RetryPolicy(), RecordingSleeper())

    reflection = await reflective.execute(_execution(), _request())
    assert reflection.attempt_count == 2

    report = await _production_runner().run(
        _input(reflection.final.outcome, reflection.final.response)
    )

    assert len(report.results) == 2, "one verdict per evaluator, not per attempt"
    assert report.target_failed is False
    assert reflection.final.response.content == {"text": "recovered"}, (
        "the evaluated outcome is the delivered one, not the discarded first attempt"
    )


async def test_an_evaluation_failure_does_not_trigger_a_retry() -> None:
    """Reflection has already finished by the time evaluation runs, and evaluation has no route
    back into it (structurally: it cannot import gateway.application.reflection)."""
    # Content-less but *settleable*: usage is present, so Slice 9 settles and Slice 10 caches it
    # normally. Only the completeness evaluator objects - which is the point. (A response with no
    # usage at all never reaches evaluation: CostAccountant raises MissingUsageError at settlement,
    # so that branch of the usage evaluator is defence in depth, not the path exercised here.)
    client = FakeProviderClient(
        responses={
            "openai": ProviderResponse(
                ok=True,
                content=None,
                provider="openai",
                usage=ProviderUsage(prompt_tokens=10, completion_tokens=5),
            )
        }
    )
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator = _coordinator(client, ledger, InMemoryResponseCache(FixedClock()))
    reflective = ReflectiveExecutor(coordinator, RetryPolicy(max_attempts=3), RecordingSleeper())

    reflection = await reflective.execute(_execution(), _request())
    calls_after_execution = len(client.calls)

    report = await _production_runner().run(
        _input(reflection.final.outcome, reflection.final.response)
    )

    assert report.target_failed is True, "the empty-content response must be judged defective"
    assert len(client.calls) == calls_after_execution, "a failed verdict must not re-run anything"
    assert reflection.attempt_count == 1
