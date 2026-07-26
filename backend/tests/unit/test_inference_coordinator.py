"""InferenceCoordinator tests (ADR-0016 Slice 10).

Exercises the full cache -> dedup -> reserve -> execute -> settle/release sequence against the
fast in-memory doubles. Real concurrency/atomicity/RLS claims for the cache are proven separately
against PostgreSQL (tests/integration/test_response_cache_postgres.py); this file proves the
coordinator's own orchestration and fail-safe semantics.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.health.in_memory_circuit_breaker import InMemoryCircuitBreaker
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.fake_client import FakeProviderClient
from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import (
    InferenceCoordinator,
    InferenceExecutionResult,
)
from gateway.application.ports.circuit_breaker import (
    CircuitState,
    ProviderCallResult,
    ProviderCircuit,
)
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.ledger import ReservationOutcome, UnknownReservationError
from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import InferenceRequest, ProviderResponse, ProviderUsage
from gateway.application.ports.routing import RoutingExecution
from gateway.application.providers.provider_executor import ProviderExecutor
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


class MovableClock:
    def __init__(self) -> None:
        self._moment = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment


def _decision(outcome: RoutingOutcome, correlation_id: str = "c1") -> RoutingDecision:
    return RoutingDecision(
        outcome=outcome,
        organization_id=ORG,
        correlation_id=correlation_id,
        decided_at=datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC),
        reasoning_steps=(ReasoningStep(agent="provider", summary="stub"),),
        selected_provider="openai" if outcome is RoutingOutcome.SELECTED else None,
    )


def _execution(
    outcome: RoutingOutcome = RoutingOutcome.SELECTED, correlation_id: str = "c1"
) -> RoutingExecution:
    provider = OPENAI if outcome is RoutingOutcome.SELECTED else None
    return RoutingExecution(decision=_decision(outcome, correlation_id), provider=provider)


def _request(correlation_id: str = "c1", prompt: str = "hello") -> InferenceRequest:
    return InferenceRequest(correlation_id=correlation_id, payload={"prompt": prompt})


def _ok_response(text: str = "world") -> ProviderResponse:
    return ProviderResponse(
        ok=True,
        content={"text": text},
        provider="openai",
        usage=ProviderUsage(prompt_tokens=10, completion_tokens=5),
    )


def _coordinator(
    client: FakeProviderClient,
    ledger: InMemoryBudgetLedger | None = None,
    cache: InMemoryResponseCache | None = None,
) -> tuple[InferenceCoordinator, InMemoryBudgetLedger]:
    if ledger is None:
        ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    if cache is None:
        cache = InMemoryResponseCache(MovableClock())
    pricing = StaticPriceTable((PRICE,))
    reservation = reservation_service(ledger, pricing)
    coordinator = InferenceCoordinator(
        cache,
        RequestDeduplicator(),
        reservation,
        ProviderExecutor(client),
        InMemoryCircuitBreaker(MovableClock()),
    )
    return coordinator, ledger


# ------------------------------------------------------------------ circuit-breaker feed (Slice 20)


class _RecordingBreaker:
    """Records every ``observe`` so a test can assert exactly which calls fed the circuit.

    ``assess`` always reports CLOSED: this double is about the *write* side (does a real provider
    call feed the breaker, and do the non-call paths correctly not?), not the state machine, which
    is covered exhaustively in ``test_circuit_breaker.py``. It satisfies the ``CircuitBreaker``
    protocol structurally.
    """

    def __init__(self) -> None:
        self.observed: list[tuple[str, bool]] = []

    def observe(self, *, organization_id: UUID, provider: str, result: ProviderCallResult) -> None:
        self.observed.append((provider, result.ok))

    def assess(
        self, *, organization_id: UUID, providers: Sequence[str]
    ) -> tuple[ProviderCircuit, ...]:
        return tuple(ProviderCircuit(provider=p, state=CircuitState.CLOSED) for p in providers)


def _coordinator_with(
    breaker: _RecordingBreaker,
    client: FakeProviderClient,
    *,
    ledger: InMemoryBudgetLedger | None = None,
) -> InferenceCoordinator:
    if ledger is None:
        ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    pricing = StaticPriceTable((PRICE,))
    return InferenceCoordinator(
        InMemoryResponseCache(MovableClock()),
        RequestDeduplicator(),
        reservation_service(ledger, pricing),
        ProviderExecutor(client),
        breaker,
    )


async def test_a_real_provider_call_feeds_its_outcome_to_the_breaker() -> None:
    breaker = _RecordingBreaker()
    client = FakeProviderClient(responses={"openai": _ok_response()})
    coordinator = _coordinator_with(breaker, client)

    await coordinator.execute(_execution(), _request())

    assert breaker.observed == [("openai", True)], "the provider's success must reach the breaker"


async def test_a_provider_failure_is_reported_to_the_breaker() -> None:
    breaker = _RecordingBreaker()
    failing = ProviderResponse(ok=False, error="boom", provider="openai")
    coordinator = _coordinator_with(breaker, FakeProviderClient(responses={"openai": failing}))

    await coordinator.execute(_execution(), _request())

    assert breaker.observed == [("openai", False)]


async def test_a_cache_hit_does_not_feed_the_breaker() -> None:
    breaker = _RecordingBreaker()
    client = FakeProviderClient(responses={"openai": _ok_response()})
    coordinator = _coordinator_with(breaker, client)
    await coordinator.execute(_execution(), _request("warm"))
    breaker.observed.clear()

    result = await coordinator.execute(_execution(correlation_id="hit"), _request("warm"))

    assert result.outcome is ExecutionOutcome.CACHE_HIT
    assert breaker.observed == [], "a cache hit calls no provider, so it must not touch the breaker"


async def test_a_budget_denial_does_not_feed_the_breaker() -> None:
    breaker = _RecordingBreaker()
    broke = InMemoryBudgetLedger({ORG: Money(Decimal("0.000001"), "USD")})
    coordinator = _coordinator_with(
        breaker, FakeProviderClient(responses={"openai": _ok_response()}), ledger=broke
    )

    result = await coordinator.execute(_execution(), _request())

    assert result.outcome is ExecutionOutcome.BUDGET_DENIED
    assert breaker.observed == [], "no provider was called, so the breaker must see nothing"


async def test_an_unrouted_request_does_not_feed_the_breaker() -> None:
    breaker = _RecordingBreaker()
    coordinator = _coordinator_with(breaker, FakeProviderClient())

    await coordinator.execute(_execution(RoutingOutcome.NO_CANDIDATE), _request())

    assert breaker.observed == []


# ------------------------------------------------------------------ not routed


async def test_not_routed_delegates_straight_to_the_executor_untouched() -> None:
    client = FakeProviderClient()
    coordinator, _ = _coordinator(client)
    execution = _execution(RoutingOutcome.NO_CANDIDATE)

    result = await coordinator.execute(execution, _request())

    assert result.outcome is ExecutionOutcome.NOT_ROUTED
    assert result.response.ok is False
    assert client.calls == []


# ------------------------------------------------------------------ cache miss / hit


async def test_cache_miss_reserves_executes_settles_and_populates_the_cache() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response()})
    coordinator, ledger = _coordinator(client)
    execution = _execution()

    result = await coordinator.execute(execution, _request())

    assert result.outcome is ExecutionOutcome.EXECUTED
    assert result.response.ok is True
    assert result.cost is not None
    assert len(client.calls) == 1
    # Budget was actually settled - re-reserving the whole original limit no longer fits.
    probe = await ledger.reserve(ORG, "probe", Money(Decimal("1000"), "USD"))
    assert probe.outcome is ReservationOutcome.EXCEEDED


async def test_a_cache_hit_never_calls_the_provider_or_touches_budget() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response()})
    coordinator, ledger = _coordinator(client)

    first = await coordinator.execute(_execution(correlation_id="c1"), _request("c1"))
    assert first.outcome is ExecutionOutcome.EXECUTED

    second = await coordinator.execute(_execution(correlation_id="c2"), _request("c2"))

    assert second.outcome is ExecutionOutcome.CACHE_HIT
    assert second.response.ok is True
    assert second.response.content == {"text": "world"}
    assert second.cost is None
    assert len(client.calls) == 1, "the provider must not be called again on a hit"
    # No reservation was ever created for c2's correlation id - nothing was gated because
    # nothing was going to be spent. release() on an unknown id raises, proving this negative.
    with pytest.raises(UnknownReservationError):
        await ledger.release(ORG, "c2")


async def test_a_cache_hit_reports_no_usage() -> None:
    """A hit never observed tokens - fabricating usage would misrepresent an event that never
    happened (the same discipline CostAccountant.MissingUsageError enforces elsewhere)."""
    client = FakeProviderClient(responses={"openai": _ok_response()})
    coordinator, _ = _coordinator(client)
    await coordinator.execute(_execution(correlation_id="c1"), _request("c1"))

    hit = await coordinator.execute(_execution(correlation_id="c2"), _request("c2"))

    assert hit.response.usage is None


async def test_materially_different_requests_do_not_share_a_cache_entry() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response("first")})
    coordinator, _ = _coordinator(client)
    await coordinator.execute(_execution(correlation_id="c1"), _request("c1", prompt="hello"))

    client.responses["openai"] = _ok_response("second")
    result = await coordinator.execute(
        _execution(correlation_id="c2"), _request("c2", prompt="bye")
    )

    assert result.outcome is ExecutionOutcome.EXECUTED
    assert len(client.calls) == 2


# ------------------------------------------------------------------ budget denial


async def test_budget_exceeded_denies_before_ever_calling_the_provider() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("0.000001"), "USD")})
    coordinator, _ = _coordinator(client, ledger)

    result = await coordinator.execute(_execution(), _request(prompt="hello world " * 100))

    assert result.outcome is ExecutionOutcome.BUDGET_DENIED
    assert result.response.ok is False
    assert client.calls == []


async def test_budget_store_unavailable_denies_before_ever_calling_the_provider() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")}, unavailable=True)
    coordinator, _ = _coordinator(client, ledger)

    result = await coordinator.execute(_execution(), _request())

    assert result.outcome is ExecutionOutcome.BUDGET_UNAVAILABLE
    assert client.calls == []


# ------------------------------------------------------------------ provider failure


async def test_a_failed_provider_call_releases_the_reservation_and_is_never_cached() -> None:
    client = FakeProviderClient(unreachable=True)
    coordinator, ledger = _coordinator(client)

    first = await coordinator.execute(_execution(correlation_id="c1"), _request("c1"))
    assert first.outcome is ExecutionOutcome.EXECUTED
    assert first.response.ok is False
    assert first.cost is None

    # The reservation was released, not settled - the full original limit fits again.
    probe = await ledger.reserve(ORG, "probe", Money(Decimal("1000"), "USD"))
    assert probe.outcome is ReservationOutcome.RESERVED
    await ledger.release(ORG, "probe")  # free it back up before the next assertion needs budget

    # A repeat of the exact same request is still a miss - a failure must never be cached.
    client.responses["openai"] = ProviderResponse(ok=False, error="still down", provider="openai")
    second = await coordinator.execute(_execution(correlation_id="c2"), _request("c2"))
    assert second.outcome is ExecutionOutcome.EXECUTED
    assert len(client.calls) == 2


# ------------------------------------------------------------------ deduplication


async def test_concurrent_duplicate_correlation_ids_call_the_provider_exactly_once() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response()})
    coordinator, _ = _coordinator(client)
    request = _request("shared")
    execution = _execution(correlation_id="shared")

    results = await asyncio.gather(
        coordinator.execute(execution, request),
        coordinator.execute(execution, request),
        coordinator.execute(execution, request),
    )

    assert len(client.calls) == 1, "a genuine concurrent duplicate must reach the provider once"
    assert all(r.outcome is ExecutionOutcome.EXECUTED for r in results)
    assert all(r.response.ok is True for r in results)


# ------------------------------------------------------------------ cache fails open


async def test_a_cache_lookup_outage_falls_through_to_the_normal_reserve_execute_path() -> None:
    """The cache being unreachable must never deny or fail a request - it just stops being
    faster than calling the provider (fail open, contrast the budget ledger's fail closed)."""
    client = FakeProviderClient(responses={"openai": _ok_response()})
    broken_cache = InMemoryResponseCache(MovableClock(), unavailable=True)
    coordinator, _ = _coordinator(client, cache=broken_cache)

    result = await coordinator.execute(_execution(), _request())

    assert result.outcome is ExecutionOutcome.EXECUTED
    assert result.response.ok is True
    assert len(client.calls) == 1


async def test_a_cache_write_outage_does_not_fail_an_otherwise_successful_request() -> None:
    client = FakeProviderClient(responses={"openai": _ok_response()})
    broken_cache = InMemoryResponseCache(MovableClock(), unavailable=True)
    coordinator, _ = _coordinator(client, cache=broken_cache)

    result = await coordinator.execute(_execution(), _request())

    # The request itself succeeded - a cache write failure is invisible to the caller.
    assert result.outcome is ExecutionOutcome.EXECUTED
    assert result.response.ok is True
    assert result.cost is not None


# ------------------------------------------------------ unaccountable calls (Phase 5 M2)


async def test_a_provider_response_with_no_usage_is_a_typed_refusal_not_an_exception() -> None:
    """Before M2 ``MissingUsageError`` escaped the coordinator, travelled untouched through
    reflection and serving, and reached HTTP as an unhandled exception - a generic 500 with the
    budget hold still reserved behind it. It is now a refusal the delivery layer can map, and the
    hold is given back."""
    client = FakeProviderClient(
        responses={"openai": ProviderResponse(ok=True, content="hi", provider="openai")}
    )
    coordinator, ledger = _coordinator(client)

    result = await coordinator.execute(_execution(), _request())

    assert result.outcome is ExecutionOutcome.NOT_ACCOUNTABLE
    assert result.response.ok is False
    assert result.cost is None
    # The hold came back: the whole original limit is reservable again.
    probe = await ledger.reserve(ORG, "probe", Money(Decimal("1000"), "USD"))
    assert probe.outcome is ReservationOutcome.RESERVED


async def test_an_unaccountable_call_is_never_cached() -> None:
    """A response nobody could price must not be served again for free."""
    client = FakeProviderClient(
        responses={"openai": ProviderResponse(ok=True, content="hi", provider="openai")}
    )
    cache = InMemoryResponseCache(MovableClock())
    coordinator, _ = _coordinator(client, cache=cache)

    await coordinator.execute(_execution(), _request())

    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    assert await cache.get(ORG, key) is None


async def test_an_unpriced_model_refuses_before_the_provider_is_called() -> None:
    """Reservation prices the call first, so the defect is caught before any spend or any call."""
    client = FakeProviderClient(responses={"openai": _ok_response()})
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    unpriced = StaticPriceTable(())
    coordinator = InferenceCoordinator(
        InMemoryResponseCache(MovableClock()),
        RequestDeduplicator(),
        reservation_service(ledger, unpriced),
        ProviderExecutor(client),
        InMemoryCircuitBreaker(MovableClock()),
    )

    result = await coordinator.execute(_execution(), _request())

    assert result.outcome is ExecutionOutcome.NOT_ACCOUNTABLE
    assert client.calls == []


def test_an_unaccountable_outcome_is_terminal_for_reflection() -> None:
    """Retrying a configuration or provider defect is precisely wrong - it would charge the tenant
    again for a call that cannot succeed until a human changes something."""
    from gateway.application.reflection.retry_policy import RetryVerdict, classify

    result = InferenceExecutionResult(
        outcome=ExecutionOutcome.NOT_ACCOUNTABLE,
        response=ProviderResponse(ok=False, error="not_accountable"),
    )

    assert classify(result) is RetryVerdict.TERMINAL_FAILURE
