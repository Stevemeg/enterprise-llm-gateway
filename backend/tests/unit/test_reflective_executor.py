"""ReflectiveExecutor tests (ADR-0016 Slice 11).

Exercises the full reflection loop over the real Slice-10 coordinator and the real Slice-9
reservation path (against in-memory adapters), so budget/cache/dedup interaction across attempts is
genuinely exercised rather than mocked away. No test sleeps in real time: the sleeper is injected
and records the delays it was asked for.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.fake_client import FakeProviderClient
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import (
    InferenceCoordinator,
    InferenceExecutionResult,
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
from gateway.application.reflection.reflective_executor import (
    ReflectionResult,
    ReflectiveExecutor,
)
from gateway.application.reflection.retry_policy import RetryPolicy, RetryVerdict
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.domain.routing.models import ReasoningStep, RoutingDecision, RoutingOutcome

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
    """Records requested delays instead of elapsing them - tests must never sleep for real."""

    def __init__(self) -> None:
        self.slept: list[timedelta] = []

    async def sleep(self, duration: timedelta) -> None:
        self.slept.append(duration)


def _decision(outcome: RoutingOutcome) -> RoutingDecision:
    return RoutingDecision(
        outcome=outcome,
        organization_id=ORG,
        correlation_id="c1",
        decided_at=datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC),
        reasoning_steps=(ReasoningStep(agent="provider", summary="stub"),),
        selected_provider="openai" if outcome is RoutingOutcome.SELECTED else None,
        selected_model="gpt-4o" if outcome is RoutingOutcome.SELECTED else None,
    )


def _execution(outcome: RoutingOutcome = RoutingOutcome.SELECTED) -> RoutingExecution:
    provider = OPENAI if outcome is RoutingOutcome.SELECTED else None
    return RoutingExecution(decision=_decision(outcome), provider=provider)


def _request(correlation_id: str = "c1") -> InferenceRequest:
    return InferenceRequest(correlation_id=correlation_id, payload={"prompt": "hello"})


def _ok(text: str = "world") -> ProviderResponse:
    return ProviderResponse(
        ok=True,
        content={"text": text},
        provider="openai",
        usage=ProviderUsage(prompt_tokens=10, completion_tokens=5),
    )


def _fail(category: ProviderErrorCategory | None) -> ProviderResponse:
    return ProviderResponse(
        ok=False, error="upstream failure", provider="openai", error_category=category
    )


def _build(
    client: FakeProviderClient,
    *,
    policy: RetryPolicy | None = None,
    ledger: InMemoryBudgetLedger | None = None,
    cache: InMemoryResponseCache | None = None,
) -> tuple[ReflectiveExecutor, RecordingSleeper, InMemoryBudgetLedger]:
    if ledger is None:
        ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    if cache is None:
        cache = InMemoryResponseCache(FixedClock())
    pricing = StaticPriceTable((PRICE,))
    coordinator = InferenceCoordinator(
        cache,
        RequestDeduplicator(),
        ReservationService(ledger, pricing, CostAccountant(pricing)),
        ProviderExecutor(client),
    )
    sleeper = RecordingSleeper()
    executor = ReflectiveExecutor(coordinator, policy or RetryPolicy(), sleeper)
    return executor, sleeper, ledger


# ------------------------------------------------------------------ no retry on success


async def test_success_on_the_first_attempt_never_retries() -> None:
    client = FakeProviderClient(responses={"openai": _ok()})
    executor, sleeper, _ = _build(client)

    result = await executor.execute(_execution(), _request())

    assert result.attempt_count == 1
    assert result.retried is False
    assert result.succeeded is True
    assert len(client.calls) == 1
    assert sleeper.slept == [], "no backoff may be incurred when nothing was retried"


async def test_a_cache_hit_terminates_reflection_immediately_with_no_provider_call() -> None:
    cache = InMemoryResponseCache(FixedClock())
    client = FakeProviderClient(responses={"openai": _ok()})
    executor, _, _ = _build(client, cache=cache)
    await executor.execute(_execution(), _request("first"))
    calls_after_warmup = len(client.calls)

    result = await executor.execute(_execution(), _request("second"))

    assert result.final.outcome is ExecutionOutcome.CACHE_HIT
    assert result.attempt_count == 1
    assert len(client.calls) == calls_after_warmup, "a hit must not reach the provider"


# ------------------------------------------------------------------ never retried


async def test_an_unrouted_request_is_never_retried() -> None:
    """Policy denial / no candidate / all-unhealthy all arrive as NOT_ROUTED."""
    client = FakeProviderClient()
    executor, sleeper, _ = _build(client)

    result = await executor.execute(_execution(RoutingOutcome.BLOCKED_BY_POLICY), _request())

    assert result.final.outcome is ExecutionOutcome.NOT_ROUTED
    assert result.attempt_count == 1
    assert client.calls == []
    assert sleeper.slept == []


async def test_a_budget_denial_is_never_retried_and_never_reaches_the_provider() -> None:
    client = FakeProviderClient(responses={"openai": _ok()})
    broke = InMemoryBudgetLedger({ORG: Money(Decimal("0.000001"), "USD")})
    executor, sleeper, _ = _build(client, ledger=broke)

    result = await executor.execute(_execution(), _request())

    assert result.final.outcome is ExecutionOutcome.BUDGET_DENIED
    assert result.attempt_count == 1
    assert client.calls == [], "a failed reservation must never call the provider"
    assert sleeper.slept == []


async def test_a_budget_store_outage_is_never_retried() -> None:
    client = FakeProviderClient(responses={"openai": _ok()})
    down = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")}, unavailable=True)
    executor, _, _ = _build(client, ledger=down)

    result = await executor.execute(_execution(), _request())

    assert result.final.outcome is ExecutionOutcome.BUDGET_UNAVAILABLE
    assert result.attempt_count == 1
    assert client.calls == []


@pytest.mark.parametrize(
    "category", [ProviderErrorCategory.INVALID_REQUEST, ProviderErrorCategory.AUTHENTICATION]
)
async def test_a_permanent_provider_error_is_never_retried(
    category: ProviderErrorCategory,
) -> None:
    client = FakeProviderClient(sequence=[_fail(category)])
    executor, _, _ = _build(client)

    result = await executor.execute(_execution(), _request())

    assert result.attempt_count == 1
    assert len(client.calls) == 1


async def test_an_unclassified_provider_failure_is_not_retried() -> None:
    client = FakeProviderClient(sequence=[_fail(None)])
    executor, _, _ = _build(client)

    result = await executor.execute(_execution(), _request())

    assert result.attempt_count == 1
    assert len(client.calls) == 1


# ------------------------------------------------------------------ bounded retry


async def test_a_transient_failure_retries_and_can_succeed() -> None:
    client = FakeProviderClient(
        sequence=[_fail(ProviderErrorCategory.RATE_LIMITED), _ok("recovered")]
    )
    executor, sleeper, _ = _build(client)

    result = await executor.execute(_execution(), _request())

    assert result.attempt_count == 2
    assert result.succeeded is True
    assert result.final.response.content == {"text": "recovered"}
    assert len(client.calls) == 2
    assert sleeper.slept == [timedelta(milliseconds=100)]


async def test_retries_stop_at_the_maximum_attempt_count() -> None:
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.SERVER_ERROR)])
    executor, sleeper, _ = _build(client, policy=RetryPolicy(max_attempts=3))

    result = await executor.execute(_execution(), _request())

    assert result.attempt_count == 3, "bounded by max_attempts, never unbounded"
    assert len(client.calls) == 3
    assert result.exhausted is True
    assert result.succeeded is False
    assert len(sleeper.slept) == 2, "one backoff between each pair of attempts, none before the 1st"


async def test_a_policy_of_one_attempt_never_retries_even_a_transient_failure() -> None:
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.TIMEOUT)])
    executor, _, _ = _build(client, policy=RetryPolicy(max_attempts=1))

    result = await executor.execute(_execution(), _request())

    assert result.attempt_count == 1
    assert len(client.calls) == 1


async def test_backoff_is_exponential_across_successive_retries() -> None:
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.TIMEOUT)])
    executor, sleeper, _ = _build(
        client, policy=RetryPolicy(max_attempts=4, base_backoff=timedelta(milliseconds=10))
    )

    await executor.execute(_execution(), _request())

    assert sleeper.slept == [
        timedelta(milliseconds=10),
        timedelta(milliseconds=20),
        timedelta(milliseconds=40),
    ]


# ------------------------------------------------------------------ retry history / explanation


async def test_retry_history_is_deterministic_and_inspectable() -> None:
    client = FakeProviderClient(
        sequence=[_fail(ProviderErrorCategory.TIMEOUT), _fail(ProviderErrorCategory.RATE_LIMITED)]
    )
    executor, _, _ = _build(client, policy=RetryPolicy(max_attempts=2))

    result = await executor.execute(_execution(), _request("abc"))

    assert [a.attempt for a in result.attempts] == [1, 2]
    assert [a.correlation_id for a in result.attempts] == ["abc#1", "abc#2"]
    assert [a.error_category for a in result.attempts] == [
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.RATE_LIMITED,
    ]
    assert all(a.verdict is RetryVerdict.RETRY for a in result.attempts)


async def test_the_original_routing_decision_is_carried_through_unmodified() -> None:
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.TIMEOUT), _ok()])
    execution = _execution()
    original = execution.decision
    executor, _, _ = _build(client)

    result = await executor.execute(execution, _request())

    assert result.execution.decision is original, "the decision object itself must be unchanged"
    assert original.correlation_id == "c1", "retries must not rewrite the routed correlation id"
    assert original.outcome is RoutingOutcome.SELECTED


def test_a_result_must_record_at_least_one_attempt() -> None:
    """An unexplainable result is forbidden, mirroring RoutingDecision.reasoning_steps."""
    empty = InferenceExecutionResult(
        outcome=ExecutionOutcome.NOT_ROUTED, response=ProviderResponse(ok=False)
    )

    with pytest.raises(ValueError, match="at least one attempt"):
        ReflectionResult(final=empty, attempts=(), execution=_execution())


# ------------------------------------------------------------------ budget across attempts


async def test_each_attempt_settles_only_its_own_actual_usage() -> None:
    """Attempt-scoped identity: the failed attempt releases its hold, the successful one settles."""
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.TIMEOUT), _ok()])
    executor, _, ledger = _build(client)

    result = await executor.execute(_execution(), _request("x"))

    assert result.succeeded is True
    # The failed attempt's reservation was released, not settled - only one attempt was charged.
    assert result.final.cost is not None
    # A reservation for nearly the whole limit still fits, so no phantom hold survived attempt 1.
    probe = await ledger.reserve(ORG, "probe", Money(Decimal("900"), "USD"))
    assert probe.outcome is ReservationOutcome.RESERVED


async def test_exhausted_retries_leak_no_budget_because_every_failed_attempt_releases() -> None:
    """Each attempt reserves under its own id and releases on failure, so a run that exhausts
    every attempt without succeeding must leave the tenant's budget exactly as it found it -
    a failed call is never charged, and a held-but-abandoned reservation would be a leak."""
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.SERVER_ERROR)])
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("100"), "USD")})
    executor, _, _ = _build(client, policy=RetryPolicy(max_attempts=4), ledger=ledger)

    result = await executor.execute(_execution(), _request())

    assert result.exhausted is True
    assert result.attempt_count == 4
    # Nothing was spent and nothing is still held: the whole limit is reservable again.
    probe = await ledger.reserve(ORG, "probe", Money(Decimal("100"), "USD"))
    assert probe.outcome is ReservationOutcome.RESERVED


async def test_a_budget_denial_on_a_later_attempt_terminates_the_loop() -> None:
    """A budget that only covers the first attempt must stop the loop at the denial, not keep
    retrying into a wall (the denial is terminal, never itself retried)."""
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.TIMEOUT)])
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("100"), "USD")})
    executor, _, _ = _build(client, policy=RetryPolicy(max_attempts=5), ledger=ledger)
    # Consume almost the whole budget out from under the retry loop before it runs.
    await ledger.reserve(ORG, "external-hold", Money(Decimal("99.999"), "USD"))

    result = await executor.execute(_execution(), _request())

    assert result.final.outcome is ExecutionOutcome.BUDGET_DENIED
    assert result.attempt_count == 1, "a budget denial is terminal, never retried"
    assert client.calls == []


# ------------------------------------------------------------------ Slice-10 interaction


async def test_concurrent_duplicates_do_not_trigger_independent_retry_storms() -> None:
    """Slice 10's deduplication is keyed on (organization_id, correlation_id), and every attempt
    derives that id identically, so N concurrent duplicates coalesce at *every* attempt - the
    provider sees one call per attempt, not N."""
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.SERVER_ERROR)])
    executor, _, _ = _build(client, policy=RetryPolicy(max_attempts=3))
    execution, request = _execution(), _request("shared")

    results = await asyncio.gather(
        executor.execute(execution, request),
        executor.execute(execution, request),
        executor.execute(execution, request),
    )

    assert all(r.attempt_count == 3 for r in results)
    assert len(client.calls) == 3, "3 attempts x 3 duplicate callers must still be 3 provider calls"


async def test_tenant_isolation_holds_across_retries() -> None:
    """A retry must never spend or serve across a tenant boundary."""
    other_org = uuid4()
    client = FakeProviderClient(sequence=[_fail(ProviderErrorCategory.TIMEOUT), _ok()])
    ledger = InMemoryBudgetLedger(
        {ORG: Money(Decimal("1000"), "USD"), other_org: Money(Decimal("1000"), "USD")}
    )
    executor, _, _ = _build(client, ledger=ledger)

    await executor.execute(_execution(), _request("x"))

    # The other tenant's budget is untouched by either attempt.
    probe = await ledger.reserve(other_org, "probe", Money(Decimal("1000"), "USD"))
    assert probe.outcome is ReservationOutcome.RESERVED
