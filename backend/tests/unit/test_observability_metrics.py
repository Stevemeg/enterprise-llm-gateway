"""Request-path observability (ADR-0016 Slice 16).

These tests assert **behaviour**, not the mere existence of a metric: a denied request must
increment the denial series and must *not* increment execution series, a provider failure must be
distinguishable from a success, and no label may carry tenant, principal, request or free-text
data.

## Prometheus isolation

The metrics are module-level singletons on the default registry, which is global process state.
Rather than reset the registry (which would fight the design and break other tests' collectors),
each test reads a **delta**: the value before the action and after. ``_value.get()`` is
prometheus_client's documented accessor for a child's current value, and a child that has never
been observed reports 0 via the same helper. Deltas are order-independent and immune to leakage
from other tests, which resetting is not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY, Counter, Histogram

from gateway.adapters.authorization.in_memory_resolver import InMemoryPermissionResolver
from gateway.adapters.authorization.null_resolver import NullPermissionResolver
from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
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
from gateway.application.evaluation.runner import EvaluationRunner
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.pipeline.runner import RequestPipeline
from gateway.application.ports.evaluation import EvaluationOutcome
from gateway.application.ports.ledger import ReservationOutcome
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
from gateway.application.reflection.retry_policy import RetryPolicy, RetryVerdict
from gateway.application.routing.catalog import InMemoryProviderCatalog, ProviderDescriptor
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.application.serving.inference_service import InferenceService
from gateway.domain.routing.models import RoutingOutcome
from gateway.observability import metrics
from gateway.observability.metrics import NOT_ADMITTED, UNCLASSIFIED, UNKNOWN

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
    async def sleep(self, duration: timedelta) -> None:
        return None


def _usage() -> ProviderUsage:
    return ProviderUsage(prompt_tokens=10, completion_tokens=5)


def _budget() -> Money:
    return Money(Decimal("100.00"), "USD")


def _sample(name: str, labels: dict[str, str]) -> float:
    """Read one sample from the default registry, treating "never observed" as 0.

    ``get_sample_value`` is prometheus_client's public accessor, so these helpers do not depend
    on the private child attributes (which differ across releases).
    """
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else float(value)


def counter_value(metric: Counter, **labels: str) -> float:
    """Current value of one counter child; 0 when it has never been observed."""
    return _sample(f"{metric._name}_total", labels)


def histogram_count(metric: Histogram, **labels: str) -> float:
    """Number of observations recorded by one histogram child."""
    return _sample(f"{metric._name}_count", labels)


def histogram_sum(metric: Histogram, **labels: str) -> float:
    """Sum of observed values for one histogram child."""
    return _sample(f"{metric._name}_sum", labels)


# --- harness ----------------------------------------------------------------------------------


class Harness:
    """The composed request path, as the container wires it."""

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
        client = FakeProviderClient(
            sequence=responses
            or [ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())]
        )
        ledger = InMemoryBudgetLedger({ORG: limit or _budget()})
        pricing = StaticPriceTable([PRICE])
        reservation = ReservationService(ledger, pricing, CostAccountant(pricing))
        self.coordinator = InferenceCoordinator(
            InMemoryResponseCache(clock),
            RequestDeduplicator(),
            reservation,
            ProviderExecutor(client),
        )
        executor = ReflectiveExecutor(
            self.coordinator, RetryPolicy(max_attempts=max_attempts), NoSleep()
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
        pipeline = RequestPipeline(
            [
                AuthorizationStage(resolver),
                PolicyStage(LocalPolicyEngine(max_request_bytes=max_request_bytes)),
                AgentRoutingStage(AgentOrchestratedRoutingEngine(catalog, runtime)),
            ]
        )
        self.evaluation = EvaluationRunner(
            [ResponseCompletenessEvaluator(), UsageAccountingConsistencyEvaluator()]
        )
        self.service = InferenceService(pipeline, executor, self.evaluation)

    async def serve(self, payload: dict[str, Any] | None = None) -> Any:
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


# --- admission / denial ------------------------------------------------------------------------


async def test_a_denied_request_increments_the_blocking_stage_and_not_execution() -> None:
    """The central observability property: a denial is visible, and execution is not."""
    blocked_before = counter_value(
        metrics.admission_stage_decisions, stage="authorization", action="block"
    )
    executed_before = counter_value(metrics.inference_attempts, outcome="executed")
    served_before = counter_value(metrics.served_requests, outcome=NOT_ADMITTED)

    await Harness(grant=False).serve()

    assert (
        counter_value(metrics.admission_stage_decisions, stage="authorization", action="block")
        == blocked_before + 1
    )
    assert counter_value(metrics.inference_attempts, outcome="executed") == executed_before
    assert counter_value(metrics.served_requests, outcome=NOT_ADMITTED) == served_before + 1


async def test_a_policy_denial_is_attributed_to_the_policy_stage() -> None:
    before = counter_value(metrics.admission_stage_decisions, stage="policy", action="block")

    await Harness(max_request_bytes=4).serve({"prompt": "a payload beyond the configured limit"})

    assert (
        counter_value(metrics.admission_stage_decisions, stage="policy", action="block")
        == before + 1
    )


async def test_an_admitted_request_records_continue_for_each_passing_stage() -> None:
    auth_before = counter_value(
        metrics.admission_stage_decisions, stage="authorization", action="continue"
    )
    routing_before = counter_value(
        metrics.admission_stage_decisions, stage="agent_routing", action="annotate"
    )

    await Harness().serve()

    assert (
        counter_value(metrics.admission_stage_decisions, stage="authorization", action="continue")
        == auth_before + 1
    )
    assert (
        counter_value(metrics.admission_stage_decisions, stage="agent_routing", action="annotate")
        == routing_before + 1
    )


# --- served terminal outcomes -------------------------------------------------------------------


async def test_a_successful_request_increments_served_executed() -> None:
    before = counter_value(metrics.served_requests, outcome="executed")

    served = await Harness().serve()

    assert served.admitted is True
    assert counter_value(metrics.served_requests, outcome="executed") == before + 1


async def test_served_duration_is_recorded_for_both_admitted_and_denied_requests() -> None:
    denied_before = histogram_count(metrics.served_request_duration_seconds, outcome=NOT_ADMITTED)
    ok_before = histogram_count(metrics.served_request_duration_seconds, outcome="executed")

    await Harness(grant=False).serve()
    await Harness().serve()

    assert (
        histogram_count(metrics.served_request_duration_seconds, outcome=NOT_ADMITTED)
        == denied_before + 1
    )
    assert (
        histogram_count(metrics.served_request_duration_seconds, outcome="executed")
        == ok_before + 1
    )


async def test_recorded_duration_is_a_real_non_negative_elapsed_time() -> None:
    before_sum = histogram_sum(metrics.served_request_duration_seconds, outcome="executed")
    before_count = histogram_count(metrics.served_request_duration_seconds, outcome="executed")

    await Harness().serve()

    delta = histogram_sum(metrics.served_request_duration_seconds, outcome="executed") - before_sum
    assert (
        histogram_count(metrics.served_request_duration_seconds, outcome="executed")
        == before_count + 1
    )
    assert delta >= 0.0
    assert delta < 60.0


# --- routing -------------------------------------------------------------------------------------


async def test_routing_terminal_outcomes_are_distinguishable() -> None:
    selected_before = counter_value(metrics.routing_decisions, outcome="selected")
    none_before = counter_value(metrics.routing_decisions, outcome="no_candidate")

    await Harness().serve()
    await Harness(candidates=[]).serve()

    assert counter_value(metrics.routing_decisions, outcome="selected") == selected_before + 1
    assert counter_value(metrics.routing_decisions, outcome="no_candidate") == none_before + 1


# --- provider -------------------------------------------------------------------------------------


async def test_provider_success_and_failure_are_distinguishable() -> None:
    ok_before = counter_value(metrics.provider_calls, provider="openai", outcome="ok")
    rate_before = counter_value(metrics.provider_calls, provider="openai", outcome="rate_limited")

    await Harness().serve()
    await Harness(
        responses=[
            ProviderResponse(
                ok=False, error="slow down", error_category=ProviderErrorCategory.RATE_LIMITED
            )
        ],
        max_attempts=1,
    ).serve()

    assert counter_value(metrics.provider_calls, provider="openai", outcome="ok") == ok_before + 1
    assert (
        counter_value(metrics.provider_calls, provider="openai", outcome="rate_limited")
        == rate_before + 1
    )


async def test_an_unclassified_provider_failure_is_recorded_as_unclassified_not_unknown() -> None:
    """``unclassified`` is a real state (error_category is None); ``unknown`` means a value fell
    outside the allowlist. Collapsing them would hide a genuine classification gap."""
    before = counter_value(metrics.provider_calls, provider="openai", outcome=UNCLASSIFIED)

    await Harness(
        responses=[ProviderResponse(ok=False, error="something broke")], max_attempts=1
    ).serve()

    assert (
        counter_value(metrics.provider_calls, provider="openai", outcome=UNCLASSIFIED) == before + 1
    )


async def test_provider_latency_is_recorded_per_provider() -> None:
    before = histogram_count(metrics.provider_call_duration_seconds, provider="openai")

    await Harness().serve()

    assert histogram_count(metrics.provider_call_duration_seconds, provider="openai") == before + 1


async def test_an_unrouted_request_records_no_provider_call() -> None:
    """No provider was invoked, so nothing may be timed or counted against one."""
    before = histogram_count(metrics.provider_call_duration_seconds, provider="openai")

    await Harness(candidates=[]).serve()

    assert histogram_count(metrics.provider_call_duration_seconds, provider="openai") == before


# --- cache / attempts / reflection ------------------------------------------------------------


async def test_cache_hit_and_miss_are_distinguishable() -> None:
    miss_before = counter_value(metrics.cache_lookups, result="miss")
    hit_before = counter_value(metrics.cache_lookups, result="hit")

    harness = Harness()
    await harness.serve()  # miss, then stores
    await harness.serve()  # hit

    assert counter_value(metrics.cache_lookups, result="miss") == miss_before + 1
    assert counter_value(metrics.cache_lookups, result="hit") == hit_before + 1


async def test_a_cache_hit_records_an_attempt_but_no_provider_call() -> None:
    harness = Harness()
    await harness.serve()
    hit_attempts_before = counter_value(metrics.inference_attempts, outcome="cache_hit")
    provider_before = counter_value(metrics.provider_calls, provider="openai", outcome="ok")

    await harness.serve()

    assert counter_value(metrics.inference_attempts, outcome="cache_hit") == hit_attempts_before + 1
    assert counter_value(metrics.provider_calls, provider="openai", outcome="ok") == provider_before


async def test_retries_are_observable_as_separate_attempts() -> None:
    retry_before = counter_value(metrics.reflection_attempts, verdict=RetryVerdict.RETRY.value)
    ok_before = counter_value(metrics.reflection_attempts, verdict=RetryVerdict.SUCCEEDED.value)

    await Harness(
        responses=[
            ProviderResponse(
                ok=False, error="timeout", error_category=ProviderErrorCategory.TIMEOUT
            ),
            ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage()),
        ]
    ).serve()

    assert (
        counter_value(metrics.reflection_attempts, verdict=RetryVerdict.RETRY.value)
        == retry_before + 1
    )
    assert (
        counter_value(metrics.reflection_attempts, verdict=RetryVerdict.SUCCEEDED.value)
        == ok_before + 1
    )


# --- budget / evaluation ----------------------------------------------------------------------


async def test_budget_denial_is_observable_and_distinct_from_success() -> None:
    reserved_before = counter_value(metrics.budget_reservations, outcome="reserved")
    exceeded_before = counter_value(metrics.budget_reservations, outcome="exceeded")

    await Harness(limit=Money(Decimal("0.00000001"), "USD"), max_attempts=1).serve()

    assert counter_value(metrics.budget_reservations, outcome="exceeded") == exceeded_before + 1
    assert counter_value(metrics.budget_reservations, outcome="reserved") == reserved_before


async def test_evaluation_outcomes_are_observable_per_evaluator() -> None:
    before = counter_value(
        metrics.evaluations,
        evaluator="response_completeness",
        outcome=EvaluationOutcome.PASSED.value,
    )

    await Harness().serve()

    assert (
        counter_value(
            metrics.evaluations,
            evaluator="response_completeness",
            outcome=EvaluationOutcome.PASSED.value,
        )
        == before + 1
    )


# --- label safety -------------------------------------------------------------------------------


async def test_no_metric_label_value_contains_tenant_principal_or_request_identity() -> None:
    """The security property, checked against the live registry rather than the source."""
    await Harness().serve()
    await Harness(grant=False).serve()

    forbidden = {str(ORG), str(PRINCIPAL), "corr-1", "hello", "hi"}
    seen = 0
    for metric in REGISTRY.collect():
        if not metric.name.startswith("gateway_"):
            continue
        for sample in metric.samples:
            for value in sample.labels.values():
                seen += 1
                assert value not in forbidden, f"{sample.name} leaked {value!r}"
    assert seen > 0


async def test_a_provider_label_cannot_be_influenced_by_the_request_payload() -> None:
    """``provider`` is catalog-supplied. A payload claiming another provider must not create a
    series - otherwise a caller controls cardinality."""
    await Harness().serve({"prompt": "hi", "provider": "attacker-controlled", "model": "evil"})

    labels = {
        sample.labels.get("provider")
        for metric in REGISTRY.collect()
        if metric.name == "gateway_provider_calls"
        for sample in metric.samples
    }
    assert "attacker-controlled" not in labels
    assert "openai" in labels


def test_an_out_of_vocabulary_value_collapses_to_unknown_instead_of_a_new_series() -> None:
    """Runtime bounding: the property the guard cannot prove statically."""
    before = counter_value(metrics.inference_attempts, outcome=UNKNOWN)

    metrics.record_inference_attempt(outcome="some_state_that_does_not_exist")

    assert counter_value(metrics.inference_attempts, outcome=UNKNOWN) == before + 1


def test_a_broken_metric_never_propagates_into_the_request_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observability must not become a correctness dependency (Slice 16 records, never decides)."""

    class Exploding:
        def labels(self, **_: str) -> Any:
            raise RuntimeError("registry exploded")

    monkeypatch.setattr(metrics, "inference_attempts", Exploding())

    metrics.record_inference_attempt(outcome="executed")  # must not raise


async def test_a_broken_metric_does_not_change_a_request_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same property end to end: the served result is identical with a broken collector."""

    class Exploding:
        def labels(self, **_: str) -> Any:
            raise RuntimeError("registry exploded")

    monkeypatch.setattr(metrics, "served_requests", Exploding())
    monkeypatch.setattr(metrics, "provider_calls", Exploding())

    served = await Harness().serve()

    assert served.admitted is True
    assert served.reflection is not None
    assert served.reflection.final.response.ok is True


# --- vocabulary/enum pairing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum_values", "allowlist"),
    [
        ({a.value for a in StageAction}, metrics._STAGE_ACTIONS),
        ({o.value for o in RoutingOutcome}, metrics._ROUTING_OUTCOMES),
        ({o.value for o in EvaluationOutcome}, metrics._EVALUATION_OUTCOMES),
        ({o.value for o in ReservationOutcome}, metrics._RESERVATION_OUTCOMES),
        ({v.value for v in RetryVerdict}, metrics._RETRY_VERDICTS),
    ],
)
def test_every_closed_enum_member_is_in_its_metric_allowlist(
    enum_values: set[str], allowlist: frozenset[str]
) -> None:
    """A new enum member must not silently start reporting as ``unknown``."""
    assert enum_values <= allowlist


def test_provider_error_categories_are_all_representable() -> None:
    assert {c.value for c in ProviderErrorCategory} <= metrics._PROVIDER_OUTCOMES


def test_metrics_module_declares_no_label_outside_the_guarded_allowlist() -> None:
    """Mirrors the guard, so a violation fails the suite as well as the gate."""
    for metric in (
        metrics.admission_stage_decisions,
        metrics.served_requests,
        metrics.inference_attempts,
        metrics.cache_lookups,
        metrics.provider_calls,
        metrics.reflection_attempts,
        metrics.routing_decisions,
        metrics.evaluations,
        metrics.budget_reservations,
    ):
        for name in metric._labelnames:
            assert name in {
                "reason",
                "method",
                "result",
                "stage",
                "action",
                "outcome",
                "provider",
                "verdict",
                "evaluator",
            }


def test_configuration_bounded_labels_are_documented_as_such() -> None:
    """``stage``, ``evaluator`` and ``provider`` are bounded by deployment configuration rather
    than by an enum. Recording that honestly is the point; this pins the claim so the set cannot
    grow silently."""
    assert sorted(metrics.CONFIGURATION_BOUNDED_LABELS) == ["evaluator", "provider", "stage"]
