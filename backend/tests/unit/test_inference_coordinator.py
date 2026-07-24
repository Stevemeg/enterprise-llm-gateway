"""InferenceCoordinator tests (ADR-0016 Slice 10).

Exercises the full cache -> dedup -> reserve -> execute -> settle/release sequence against the
fast in-memory doubles. Real concurrency/atomicity/RLS claims for the cache are proven separately
against PostgreSQL (tests/integration/test_response_cache_postgres.py); this file proves the
coordinator's own orchestration and fail-safe semantics.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
        selected_model="gpt-4o" if outcome is RoutingOutcome.SELECTED else None,
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
    reservation_service = ReservationService(ledger, pricing, CostAccountant(pricing))
    coordinator = InferenceCoordinator(
        cache, RequestDeduplicator(), reservation_service, ProviderExecutor(client)
    )
    return coordinator, ledger


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
