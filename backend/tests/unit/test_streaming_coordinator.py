"""StreamingCoordinator tests (Phase 5 M1).

Failure cases first, because the questions this milestone had to answer are all failure questions:
does a mid-stream failure release the hold, does a partial stream poison the cache, does a client
who walks away leave money reserved, and can a stream ever reach a provider without paying the
budget gate first.

Real concurrency/atomicity/RLS claims for the ledger and cache are proven separately against
PostgreSQL; this file proves the coordinator's own sequence and its money-safety under every way a
stream can end.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
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
from gateway.application.ports.cache import CachedResponse, CacheKey, CacheUnavailableError
from gateway.application.ports.circuit_breaker import (
    CircuitBreaker,
    ProviderCallResult,
    ProviderCircuit,
)
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.ledger import LedgerUnavailableError, ReservationOutcome
from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderUsage,
)
from gateway.application.ports.routing import RoutingExecution
from gateway.application.ports.streaming import (
    InferenceStreamEvent,
    ProviderStreamEvent,
    StreamChunk,
    StreamCompleted,
    StreamFailed,
)
from gateway.application.providers.streaming_executor import StreamingProviderExecutor
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.application.streaming.streaming_coordinator import (
    StreamingCoordinator,
    StreamSession,
)
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


class FrozenClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


def _decision(outcome: RoutingOutcome, correlation_id: str = "c1") -> RoutingDecision:
    return RoutingDecision(
        outcome=outcome,
        organization_id=ORG,
        correlation_id=correlation_id,
        decided_at=datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC),
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


def _usage() -> ProviderUsage:
    return ProviderUsage(prompt_tokens=10, completion_tokens=5)


class RecordingBreaker:
    """Records what the coordinator reported, so "the breaker was never told" is assertable."""

    def __init__(self) -> None:
        self.observations: list[ProviderCallResult] = []

    def observe(self, *, organization_id: UUID, provider: str, result: ProviderCallResult) -> None:
        self.observations.append(result)

    def assess(
        self, *, organization_id: UUID, providers: Sequence[str]
    ) -> tuple[ProviderCircuit, ...]:  # pragma: no cover - must never be reached
        raise AssertionError(
            "the streaming coordinator reports health; reading it is the HealthAgent's job"
        )


def _build(
    events: list[ProviderStreamEvent],
    *,
    ledger: InMemoryBudgetLedger | None = None,
    cache: InMemoryResponseCache | None = None,
    breaker: RecordingBreaker | None = None,
) -> tuple[StreamingCoordinator, InMemoryBudgetLedger, InMemoryResponseCache, FakeProviderClient]:
    ledger = ledger or InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    cache = cache or InMemoryResponseCache(FrozenClock())
    pricing = StaticPriceTable((PRICE,))
    client = FakeProviderClient(stream_events=events)
    circuit: CircuitBreaker = breaker or InMemoryCircuitBreaker(FrozenClock())
    coordinator = StreamingCoordinator(
        cache,
        reservation_service(ledger, pricing),
        StreamingProviderExecutor(client),
        circuit,
    )
    return coordinator, ledger, cache, client


async def _drain(session: StreamSession) -> list[InferenceStreamEvent]:
    assert session.events is not None
    return [event async for event in session.events]


#: The org's whole budget in these tests. Every money assertion is expressed against it.
LIMIT = Decimal("1000")
#: What ``{'prompt': 'hello'}`` estimates to, and therefore what a live hold costs:
#: 19 chars // 4 = 4 prompt tokens, 4 completion tokens -> 4/1k x 1 + 4/1k x 2.
HELD = Decimal("0.012")
#: What ``_usage()`` actually settles to: 10/1k x 1 + 5/1k x 2.
SPENT = Decimal("0.02")


async def _remaining(ledger: InMemoryBudgetLedger) -> Decimal:
    """The org's remaining budget, read through the **port**, never through its internals.

    An over-large reservation is refused and reports exactly what was left, and a refused
    reservation holds nothing (``BudgetLedgerPort.reserve``), so this observes without disturbing.
    Three outcomes are then distinguishable, which is the whole point: ``LIMIT`` means the hold
    came back, ``LIMIT - SPENT`` means it was settled, and ``LIMIT - HELD`` means it leaked.
    """
    probe = await ledger.reserve(ORG, f"probe-{uuid4()}", Money(Decimal("1000000"), "USD"))
    assert probe.outcome is ReservationOutcome.EXCEEDED
    assert probe.remaining is not None
    return probe.remaining.amount


# ---------------------------------------------------------------- the budget gate comes first


async def test_a_denied_reservation_never_reaches_the_provider() -> None:
    """The property the whole milestone rests on: no stream can outrun the budget gate."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("0"), "USD")})
    coordinator, _, _, client = _build(
        [StreamChunk(content="never"), StreamCompleted(_usage())], ledger=ledger
    )

    session = await coordinator.open(_execution(), _request())

    assert session.outcome is ExecutionOutcome.BUDGET_DENIED
    assert session.opened is False
    assert client.stream_calls == []


async def test_an_unrouted_execution_never_reaches_the_provider() -> None:
    coordinator, ledger, _, client = _build([StreamCompleted(_usage())])

    session = await coordinator.open(_execution(RoutingOutcome.NO_CANDIDATE), _request())

    assert session.outcome is ExecutionOutcome.NOT_ROUTED
    assert session.opened is False
    assert client.stream_calls == []
    assert await _remaining(ledger) == LIMIT


# ---------------------------------------------------------------- failures before the first chunk


async def test_a_failure_before_the_first_chunk_is_a_refusal_not_a_stream() -> None:
    """Nothing escaped, so the caller still gets a status code - and the hold goes back."""
    breaker = RecordingBreaker()
    coordinator, ledger, cache, _ = _build(
        [StreamFailed(error="boom", error_category=ProviderErrorCategory.SERVER_ERROR)],
        breaker=breaker,
    )

    session = await coordinator.open(_execution(), _request())

    assert session.opened is False
    assert session.outcome is ExecutionOutcome.EXECUTED
    assert session.error_category is ProviderErrorCategory.SERVER_ERROR
    assert await _remaining(ledger) == LIMIT
    assert [o.ok for o in breaker.observations] == [False]
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    assert await cache.get(ORG, key) is None


async def test_a_stream_that_says_nothing_at_all_is_a_refusal() -> None:
    """An empty script is a provider that opened a stream and then stopped. It is not a success,
    and it must not be mistaken for an empty completion."""
    coordinator, ledger, _, _ = _build([])

    session = await coordinator.open(_execution(), _request())

    assert session.opened is False
    assert session.error is not None
    assert await _remaining(ledger) == LIMIT


# ---------------------------------------------------------------- the happy path


async def test_a_completed_stream_yields_its_chunks_settles_once_and_caches() -> None:
    breaker = RecordingBreaker()
    coordinator, ledger, cache, _ = _build(
        [StreamChunk(content="he"), StreamChunk(content="llo"), StreamCompleted(_usage())],
        breaker=breaker,
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert session.outcome is ExecutionOutcome.EXECUTED
    assert [e.content for e in events if isinstance(e, StreamChunk)] == ["he", "llo"]
    assert not any(isinstance(e, StreamFailed) for e in events)
    assert await _remaining(ledger) == LIMIT - SPENT
    assert [o.ok for o in breaker.observations] == [True]

    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    stored = await cache.get(ORG, key)
    assert stored is not None
    assert stored.content == "hello"


async def test_settlement_charges_the_usage_the_provider_reported() -> None:
    """10 prompt tokens at 1/1k + 5 completion tokens at 2/1k = 0.02, and the estimate that was
    held is given back in full - the reserve-high/settle-actual shape, over a stream."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    coordinator, _, _, _ = _build(
        [StreamChunk(content="hi"), StreamCompleted(_usage())], ledger=ledger
    )

    session = await coordinator.open(_execution(), _request())
    await _drain(session)

    # The estimate that was held is fully returned and only the actual usage is charged.
    assert await _remaining(ledger) == LIMIT - SPENT


# ---------------------------------------------------------------- failures after the commit


async def test_a_failure_after_the_first_chunk_ends_the_stream_and_releases() -> None:
    """Committed: the client already has part of an answer, so the failure is a terminal event
    inside the stream rather than a status code - and nothing is cached or charged."""
    breaker = RecordingBreaker()
    coordinator, ledger, cache, _ = _build(
        [
            StreamChunk(content="par"),
            StreamFailed(error="upstream died", error_category=ProviderErrorCategory.TIMEOUT),
        ],
        breaker=breaker,
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert session.opened is True
    assert isinstance(events[-1], StreamFailed)
    assert await _remaining(ledger) == LIMIT
    assert [o.error_category for o in breaker.observations] == [ProviderErrorCategory.TIMEOUT]
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    assert await cache.get(ORG, key) is None


async def test_a_truncated_stream_is_not_a_completion() -> None:
    """Chunks then silence. The partial text must never be cached as if it were the whole answer."""
    coordinator, ledger, cache, _ = _build([StreamChunk(content="half an ans")])

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert isinstance(events[-1], StreamFailed)
    assert await _remaining(ledger) == LIMIT
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    assert await cache.get(ORG, key) is None


async def test_a_stream_that_completes_without_usage_is_released_not_settled() -> None:
    """Usage is never reconstructed from the text that was produced: an estimate is a routing
    input, not a charge. The hold goes back and the client is told the answer is unaccountable."""
    coordinator, ledger, cache, _ = _build(
        [StreamChunk(content="text"), StreamCompleted(usage=None)]
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert isinstance(events[-1], StreamFailed)
    assert await _remaining(ledger) == LIMIT
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    assert await cache.get(ORG, key) is None


async def test_an_unpriced_model_is_a_typed_refusal_not_an_escaping_exception() -> None:
    """Phase 5 M2. Reservation prices the call before the provider is opened, so a missing price
    stops the stream before it starts - and it stops it as ``NOT_ACCOUNTABLE``, which the delivery
    layer can turn into a status code, rather than as an exception that becomes a generic 500."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    client = FakeProviderClient(stream_events=[StreamCompleted(_usage())])
    coordinator = StreamingCoordinator(
        InMemoryResponseCache(FrozenClock()),
        reservation_service(ledger, StaticPriceTable(())),
        StreamingProviderExecutor(client),
        InMemoryCircuitBreaker(FrozenClock()),
    )

    session = await coordinator.open(_execution(), _request())

    assert session.outcome is ExecutionOutcome.NOT_ACCOUNTABLE
    assert session.opened is False
    assert client.stream_calls == []
    assert await _remaining(ledger) == LIMIT


# ---------------------------------------------------------------- cancellation


class _StallingClient:
    """Yields one chunk, then hangs forever - a provider that has started answering and stopped.

    The realistic shape for both cancellation cases: the consumer is suspended *inside*
    ``__anext__`` waiting for the next token, which is where a disconnect or an idle timeout
    actually lands.
    """

    def __init__(self) -> None:
        self.closed = False

    async def stream(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        try:
            yield StreamChunk(content="tick")
            await asyncio.Event().wait()
        finally:
            self.closed = True


def _stalled_coordinator(
    ledger: InMemoryBudgetLedger, client: _StallingClient
) -> StreamingCoordinator:
    pricing = StaticPriceTable((PRICE,))
    return StreamingCoordinator(
        InMemoryResponseCache(FrozenClock()),
        reservation_service(ledger, pricing),
        StreamingProviderExecutor(client),
        InMemoryCircuitBreaker(FrozenClock()),
    )


async def test_a_consumer_that_closes_the_stream_releases_the_hold_and_aborts_the_provider() -> (
    None
):
    """Client disconnect: Starlette closes the response generator, which closes ours. The hold
    must come back *and* the upstream call must actually be aborted - a connection left open is a
    provider call still being paid for by someone."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    client = _StallingClient()
    coordinator = _stalled_coordinator(ledger, client)

    session = await coordinator.open(_execution(), _request())
    assert session.events is not None
    assert isinstance(await anext(session.events), StreamChunk)

    await session.events.aclose()  # type: ignore[attr-defined]

    assert await _remaining(ledger) == LIMIT
    assert client.closed is True


async def test_cancelling_a_task_awaiting_the_next_chunk_releases_the_hold() -> None:
    """A real ``Task.cancel()`` against a task genuinely suspended inside ``__anext__`` - not a
    helper named "cancel". The cancellation is delivered into the generator at its yield point, so
    its finalizer runs and gives the hold back. This is where an idle timeout or a disconnect
    actually lands."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    client = _StallingClient()
    coordinator = _stalled_coordinator(ledger, client)
    session = await coordinator.open(_execution(), _request())
    assert session.events is not None
    received = asyncio.Event()

    async def consume() -> None:
        assert session.events is not None
        async for _ in session.events:
            received.set()

    task = asyncio.create_task(consume())
    await received.wait()
    await asyncio.sleep(0)  # let the consumer settle into the next __anext__
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _remaining(ledger) == LIMIT
    assert client.closed is True


async def test_a_stream_abandoned_without_being_closed_leaks_its_hold() -> None:
    """The honest negative. If a consumer is cancelled *between* events and never closes the
    generator, no finalizer runs promptly and the hold stays reserved.

    This is not a defect this milestone can close from inside the request path - nobody is left to
    run the release - and it is exactly the case reservation reconciliation (Phase 5 M2) exists to
    reclaim. Asserted rather than hoped for, so a future change that silently made it worse (or
    quietly fixed it) has to update this test and say so.
    """
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    client = _StallingClient()
    coordinator = _stalled_coordinator(ledger, client)
    session = await coordinator.open(_execution(), _request())
    assert session.events is not None
    started = asyncio.Event()

    async def consume() -> None:
        assert session.events is not None
        async for _ in session.events:
            started.set()
            await asyncio.Event().wait()  # cancelled here, outside the generator

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await _remaining(ledger) == LIMIT - HELD


# ---------------------------------------------------------------- cache


async def test_a_cache_hit_is_streamed_without_touching_the_provider_or_the_budget() -> None:
    cache = InMemoryResponseCache(FrozenClock())
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    await cache.put(ORG, key, CachedResponse(provider="openai", model="gpt-4o", content="cached"))
    coordinator, ledger, _, client = _build([StreamCompleted(_usage())], cache=cache)

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert session.outcome is ExecutionOutcome.CACHE_HIT
    assert [e.content for e in events if isinstance(e, StreamChunk)] == ["cached"]
    assert client.stream_calls == []
    assert await _remaining(ledger) == LIMIT


async def test_a_non_text_cache_entry_is_treated_as_a_miss() -> None:
    """The unary path stores whatever the provider returned, which may be a dict. This path cannot
    frame that as chunks, so it re-executes rather than inventing a serialization."""
    cache = InMemoryResponseCache(FrozenClock())
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    await cache.put(
        ORG, key, CachedResponse(provider="openai", model="gpt-4o", content={"text": "x"})
    )
    coordinator, _, _, client = _build(
        [StreamChunk(content="fresh"), StreamCompleted(_usage())], cache=cache
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert session.outcome is ExecutionOutcome.EXECUTED
    assert [e.content for e in events if isinstance(e, StreamChunk)] == ["fresh"]
    assert len(client.stream_calls) == 1


async def test_two_concurrent_streams_do_not_cross_talk() -> None:
    """No deduplicator here by design, so the guarantee that matters is isolation: each consumer
    receives its own stream's chunks in its own order, with per-request state kept apart."""
    pricing = StaticPriceTable((PRICE,))
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    reservation = reservation_service(ledger, pricing)

    async def run(correlation_id: str, text: str) -> list[str]:
        coordinator = StreamingCoordinator(
            InMemoryResponseCache(FrozenClock()),
            reservation,
            StreamingProviderExecutor(
                FakeProviderClient(
                    stream_events=[
                        StreamChunk(content=f"{text}-1"),
                        StreamChunk(content=f"{text}-2"),
                        StreamCompleted(_usage()),
                    ]
                )
            ),
            InMemoryCircuitBreaker(FrozenClock()),
        )
        session = await coordinator.open(
            _execution(correlation_id=correlation_id),
            _request(correlation_id=correlation_id, prompt=text),
        )
        assert session.events is not None
        return [e.content async for e in session.events if isinstance(e, StreamChunk)]

    left, right = await asyncio.gather(run("a", "alpha"), run("b", "beta"))

    assert left == ["alpha-1", "alpha-2"]
    assert right == ["beta-1", "beta-2"]
    # Both settled, neither left a hold: two settlements at SPENT each, nothing reserved.
    assert await _remaining(ledger) == LIMIT - (SPENT * 2)


# ---------------------------------------------------------------- infrastructure that misbehaves


class _BrokenCache:
    """A cache that cannot be reached, on read or on write."""

    async def get(self, organization_id: UUID, key: CacheKey) -> CachedResponse | None:
        raise CacheUnavailableError("simulated cache outage")

    async def put(self, organization_id: UUID, key: CacheKey, response: CachedResponse) -> None:
        raise CacheUnavailableError("simulated cache outage")


async def test_a_cache_outage_is_a_miss_on_read_and_a_dropped_write() -> None:
    """The cache fails open (unlike the ledger): losing a speed-up is never a reason to fail a
    request that would otherwise have succeeded. The stream still settles exactly once."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    pricing = StaticPriceTable((PRICE,))
    coordinator = StreamingCoordinator(
        _BrokenCache(),
        reservation_service(ledger, pricing),
        StreamingProviderExecutor(
            FakeProviderClient(stream_events=[StreamChunk(content="hi"), StreamCompleted(_usage())])
        ),
        InMemoryCircuitBreaker(FrozenClock()),
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert session.outcome is ExecutionOutcome.EXECUTED
    assert [e.content for e in events if isinstance(e, StreamChunk)] == ["hi"]
    assert not any(isinstance(e, StreamFailed) for e in events)
    assert await _remaining(ledger) == LIMIT - SPENT


class _UnsettleableLedger(InMemoryBudgetLedger):
    """Reserves and releases normally but cannot settle - the shape of a ledger that goes away
    between the reservation and the end of a long stream."""

    async def settle(self, organization_id: UUID, correlation_id: str, detail: object) -> None:
        raise LedgerUnavailableError("simulated ledger outage at settlement")


async def test_a_stream_that_cannot_be_settled_releases_and_ends_with_an_error() -> None:
    """Neither half-charged nor silently free: the hold is handed back and the client is told the
    answer could not be accounted for. Nothing is cached, because nothing was paid for."""
    ledger = _UnsettleableLedger({ORG: Money(Decimal("1000"), "USD")})
    cache = InMemoryResponseCache(FrozenClock())
    pricing = StaticPriceTable((PRICE,))
    coordinator = StreamingCoordinator(
        cache,
        reservation_service(ledger, pricing),
        StreamingProviderExecutor(
            FakeProviderClient(stream_events=[StreamChunk(content="hi"), StreamCompleted(_usage())])
        ),
        InMemoryCircuitBreaker(FrozenClock()),
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert isinstance(events[-1], StreamFailed)
    assert await _remaining(ledger) == LIMIT
    key = compute_cache_key(ORG, provider="openai", model="gpt-4o", payload={"prompt": "hello"})
    assert await cache.get(ORG, key) is None


class _UnreleasableLedger(InMemoryBudgetLedger):
    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        raise LedgerUnavailableError("simulated ledger outage at release")


async def test_a_ledger_that_cannot_release_does_not_break_the_stream() -> None:
    """The hold is then stale rather than lost - reconciliation's problem, not the client's. What
    must not happen is the outage escaping into the response as an unhandled error."""
    ledger = _UnreleasableLedger({ORG: Money(Decimal("1000"), "USD")})
    pricing = StaticPriceTable((PRICE,))
    coordinator = StreamingCoordinator(
        InMemoryResponseCache(FrozenClock()),
        reservation_service(ledger, pricing),
        StreamingProviderExecutor(
            FakeProviderClient(
                stream_events=[
                    StreamChunk(content="hi"),
                    StreamFailed(error="boom", error_category=ProviderErrorCategory.SERVER_ERROR),
                ]
            )
        ),
        InMemoryCircuitBreaker(FrozenClock()),
    )

    session = await coordinator.open(_execution(), _request())
    events = await _drain(session)

    assert isinstance(events[-1], StreamFailed)
    assert await _remaining(ledger) == LIMIT - HELD  # the hold is stale, awaiting reconciliation
