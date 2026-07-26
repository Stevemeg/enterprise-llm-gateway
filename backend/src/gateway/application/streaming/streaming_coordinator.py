"""StreamingCoordinator - cache -> reserve -> stream -> settle/release (Phase 5 Milestone 1).

The streaming analogue of ``InferenceCoordinator``, composing the *same* capabilities, unchanged:

* ``ResponseCachePort``         - the same cache, the same keys, the same entries (Slice 10).
* ``ReservationService``        - the same budget gate (Slice 9); still the only budget authority.
* ``StreamingProviderExecutor`` - the only thing that opens a provider stream (M1).
* ``CircuitBreaker``            - the same shared instance the HealthAgent reads (Slice 20).

It adds no intelligence of its own. It does not route (an unrouted ``RoutingExecution`` is refused
before anything else happens), does not price, does not compute cost, and does not decide HTTP
anything. What it *does* own, and what makes it a separate class rather than a branch inside
``InferenceCoordinator``, is the one question a unary call never has to ask:

## When does a stream become committed?

**A stream is committed the moment its first ``StreamChunk`` is handed to the delivery layer.**
Before that instant nothing has escaped the process, so a failure is an ordinary refusal: the hold
is released and the caller gets a normal error response with a status code. After that instant the
client already holds part of a provider's answer, and the only honest ending is to close the stream
with a terminal error event - never to start a second provider call whose output would be spliced
onto the first provider's partial answer and returned as one response.

That boundary is enforced **structurally, not by a flag**: this package cannot import
``gateway.application.reflection`` at all (import-linter, M1), so there is no path by which a
stream can be retried or replayed onto another attempt - committed or not. The stricter rule
("never replay") was chosen over the weaker one the API contract allows ("replay only before the
first byte") for a concrete reason rather than caution: ``ReflectiveExecutor`` retries **the same
provider**, never a different one (see its docstring - rerouting would need a second
``RoutingDecision`` for one request). A pre-first-chunk retry against the same provider is
therefore not the "failover before first byte" ``docs/API_Streaming.md`` describes; it is the same
call again. Building a second retry loop here to approximate it would be a duplicate orchestration
path with no capability the unary path does not already have. Pre-first-chunk *failover* needs a
rerouting owner, which does not exist yet - deferred with the reason recorded, not silently
skipped.

## Deduplication is deliberately absent, and that is not an oversight

``RequestDeduplicator`` coalesces concurrent duplicates by having every caller await one shared
``asyncio.Task`` **result**. A stream is not a result: two callers cannot await one iterator without
one of them stealing the other's chunks. Coalescing streams would require a broadcast/fan-out
buffer - a new mechanism, with no consumer asking for it (Rule 5). Two concurrent streaming
requests sharing a ``correlation_id`` therefore each open their own provider stream, and
``SqlBudgetLedger``'s reservation idempotency remains the durable backstop against double-charging
(exactly the guarantee the deduplicator's own docstring names for the cross-process case it cannot
cover either).

## Cache semantics

A hit is served through the streaming API as a single chunk and never calls a provider, never
reserves and never settles - a hit incurred no usage, the same reasoning ``InferenceCoordinator``
already applies. A hit whose stored content is not text is treated as a miss: the entry is real but
this path cannot frame it as chunks, which is the same "nothing usable here" answer the port
already documents for an unparseable entry.

Only a **completed, accounted** stream is written back. The write is reachable from exactly one
place - after the terminal ``StreamCompleted`` has been settled - so a partial, failed, cancelled
or unaccountable stream cannot produce an entry that a later reader would take for a whole answer.
Assembling the text to write it means buffering the whole response in memory for the life of the
request: bounded by one response, identical to what the unary path already holds, and the price of
having one cache rather than a second streaming-only one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.execution.inference_coordinator import (
    ACCOUNTING_DEFECTS,
    NOT_ACCOUNTABLE_ERROR,
)
from gateway.application.ports.cache import (
    CachedResponse,
    CacheKey,
    CacheUnavailableError,
    ResponseCachePort,
)
from gateway.application.ports.circuit_breaker import CircuitBreaker, ProviderCallResult
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.ledger import (
    LedgerUnavailableError,
    ReservationOutcome,
    UnknownReservationError,
)
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
    ProviderUsage,
)
from gateway.application.ports.routing import RoutingExecution
from gateway.application.ports.streaming import (
    InferenceStreamEvent,
    ProviderStreamEvent,
    StreamChunk,
    StreamFailed,
)
from gateway.application.providers.streaming_executor import (
    StreamingProviderExecutor,
    aclose_stream,
)
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.logging import get_logger
from gateway.observability.metrics import record_cache_lookup, record_inference_attempt

_logger = get_logger("streaming")

#: Adapter-independent failure text. Every string a caller can see is one of these constants or an
#: adapter's own constant - never a provider body, never an exception's ``str()`` (NFR-SEC03).
_MALFORMED_STREAM = "provider ended the stream without a terminal event"
_NO_USAGE = "provider ended the stream without reporting usage"
_UNACCOUNTABLE = "the completed stream could not be accounted for"


@dataclass(frozen=True, slots=True)
class StreamSession:
    """The result of *opening* a stream: either a refusal, or an iterator of events.

    Separating the opening from the streaming is what lets the delivery layer choose an HTTP status
    before it commits to a response body. Once ``events`` is non-``None`` the transport is
    committed to 200 + an event stream, and every later problem is a terminal event inside it -
    which is precisely the commit boundary, expressed as a type rather than as a convention.
    """

    outcome: ExecutionOutcome
    events: AsyncIterator[InferenceStreamEvent] | None = None
    error: str | None = None
    error_category: ProviderErrorCategory | None = None

    @property
    def opened(self) -> bool:
        return self.events is not None


class StreamingCoordinator:
    """Opens a streamed inference: cache hit, budget refusal, or a settled provider stream."""

    def __init__(
        self,
        cache: ResponseCachePort,
        reservation_service: ReservationService,
        executor: StreamingProviderExecutor,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._cache = cache
        self._reservation_service = reservation_service
        self._executor = executor
        self._circuit_breaker = circuit_breaker

    async def open(self, execution: RoutingExecution, request: InferenceRequest) -> StreamSession:
        """Run everything that must happen *before* the first byte, and report what it decided."""
        provider = execution.provider
        if not execution.routed or provider is None:
            record_inference_attempt(outcome=ExecutionOutcome.NOT_ROUTED.value)
            return StreamSession(
                outcome=ExecutionOutcome.NOT_ROUTED,
                error=f"not_routed: {execution.decision.outcome.value}",
            )

        organization_id = execution.decision.organization_id
        key = compute_cache_key(
            organization_id, provider=provider.name, model=provider.model, payload=request.payload
        )

        replayable = await self._replayable(organization_id, key)
        record_cache_lookup(hit=replayable is not None)
        if replayable is not None:
            record_inference_attempt(outcome=ExecutionOutcome.CACHE_HIT.value)
            return StreamSession(outcome=ExecutionOutcome.CACHE_HIT, events=_replay(replayable))

        try:
            reservation = await self._reservation_service.reserve(
                organization_id=organization_id, provider=provider, request=request
            )
        except ACCOUNTING_DEFECTS as exc:
            # Phase 5 M2: symmetric with the unary path. An unpriced model is a fail-closed
            # refusal with a status code, not an uncaught exception rendered as a generic 500 -
            # and it happens before the provider is opened, so there is nothing to undo.
            _logger.error(
                "stream_not_accountable",
                phase="reserve",
                provider=provider.name,
                model=provider.model,
                reason=type(exc).__name__,
            )
            record_inference_attempt(outcome=ExecutionOutcome.NOT_ACCOUNTABLE.value)
            return StreamSession(
                outcome=ExecutionOutcome.NOT_ACCOUNTABLE, error=NOT_ACCOUNTABLE_ERROR
            )
        if not reservation.permitted:
            outcome = (
                ExecutionOutcome.BUDGET_UNAVAILABLE
                if reservation.outcome is ReservationOutcome.UNAVAILABLE
                else ExecutionOutcome.BUDGET_DENIED
            )
            record_inference_attempt(outcome=outcome.value)
            # The provider is never reached: this return is above every call site of the executor.
            return StreamSession(outcome=outcome, error=f"budget_{reservation.outcome.value}")

        stream = self._executor.stream(provider, request)
        first = await anext(stream, None)
        record_inference_attempt(outcome=ExecutionOutcome.EXECUTED.value)

        if first is None or isinstance(first, StreamFailed):
            # Failed before the first chunk: nothing has escaped, so this is still an ordinary
            # refusal with a status code rather than a half-delivered response.
            failure = (
                first if isinstance(first, StreamFailed) else StreamFailed(error=_MALFORMED_STREAM)
            )
            await aclose_stream(stream)
            self._observe(organization_id, provider, ok=False, category=failure.error_category)
            await self._release(organization_id, request.correlation_id)
            return StreamSession(
                outcome=ExecutionOutcome.EXECUTED,
                error=failure.error,
                error_category=failure.error_category,
            )

        return StreamSession(
            outcome=ExecutionOutcome.EXECUTED,
            events=self._deliver(
                organization_id=organization_id,
                provider=provider,
                correlation_id=request.correlation_id,
                key=key,
                stream=stream,
                first=first,
            ),
        )

    async def _deliver(
        self,
        *,
        organization_id: UUID,
        provider: ProviderDescriptor,
        correlation_id: str,
        key: CacheKey,
        stream: AsyncIterator[ProviderStreamEvent],
        first: ProviderStreamEvent,
    ) -> AsyncIterator[InferenceStreamEvent]:
        """Relay the provider's events and finalize the reservation exactly once.

        ``finalized`` is the exactly-once guard: every path out of the loop sets it before leaving,
        so the ``finally`` clause only acts on the one case the loop cannot reach - the consumer
        walking away (client disconnect, or the serving task being cancelled) while the stream is
        still open. Releasing there is correct and releasing twice would not be: a hold that has
        already been settled must not be handed back.
        """
        buffered: list[str] = []
        finalized = False
        event: ProviderStreamEvent | None = first
        try:
            while event is not None:
                if isinstance(event, StreamChunk):
                    buffered.append(event.content)
                    # The commit boundary: past this yield, output has escaped the process.
                    yield event
                elif isinstance(event, StreamFailed):
                    self._observe(
                        organization_id, provider, ok=False, category=event.error_category
                    )
                    await self._release(organization_id, correlation_id)
                    finalized = True
                    yield event
                    return
                else:
                    terminal = await self._complete(
                        organization_id=organization_id,
                        provider=provider,
                        correlation_id=correlation_id,
                        key=key,
                        usage=event.usage,
                        content="".join(buffered),
                    )
                    finalized = True
                    if terminal is not None:
                        yield terminal
                    return
                event = await anext(stream, None)

            # The provider stopped without saying whether it was done. Not a completion: nothing
            # may be cached and nothing may be settled from output nobody vouched for.
            self._observe(organization_id, provider, ok=False, category=None)
            await self._release(organization_id, correlation_id)
            finalized = True
            yield StreamFailed(error=_MALFORMED_STREAM)
        finally:
            if not finalized:
                # Abandoned mid-stream. Not a provider fault, so the circuit breaker is not fed:
                # the provider was answering perfectly well when the client went away.
                await self._release(organization_id, correlation_id)
            await aclose_stream(stream)

    async def _complete(
        self,
        *,
        organization_id: UUID,
        provider: ProviderDescriptor,
        correlation_id: str,
        key: CacheKey,
        usage: ProviderUsage | None,
        content: str,
    ) -> StreamFailed | None:
        """Settle a normally-ended stream and cache it. Returns a terminal event if it cannot."""
        self._observe(organization_id, provider, ok=True, category=None)

        if usage is None:
            # Never reconstruct usage from the text that was produced: an estimate is a routing
            # input, not an accounting fact, and billing one would launder a guess into a charge.
            # The hold is given back rather than left hanging, and the client is told the answer
            # is not trustworthy.
            await self._release(organization_id, correlation_id)
            _logger.error("stream_completed_without_usage", provider=provider.name)
            return StreamFailed(error=_NO_USAGE)

        response = ProviderResponse(ok=True, content=content, provider=provider.name, usage=usage)
        try:
            await self._reservation_service.settle(
                organization_id=organization_id,
                correlation_id=correlation_id,
                response=response,
                provider=provider,
            )
        except (*ACCOUNTING_DEFECTS, UnknownReservationError, LedgerUnavailableError) as exc:
            await self._release(organization_id, correlation_id)
            _logger.error("stream_settlement_failed", reason=type(exc).__name__)
            return StreamFailed(error=_UNACCOUNTABLE)

        # Reachable from here only: a stream that completed, reported usage, and settled.
        await self._safe_put(
            organization_id,
            key,
            CachedResponse(provider=provider.name, model=provider.model, content=content),
        )
        return None

    def _observe(
        self,
        organization_id: UUID,
        provider: ProviderDescriptor,
        *,
        ok: bool,
        category: ProviderErrorCategory | None,
    ) -> None:
        """Feed the shared breaker. Only a real provider stream reaches here - never a cache hit,
        a budget refusal or an unrouted request, so a circuit still moves only on evidence."""
        self._circuit_breaker.observe(
            organization_id=organization_id,
            provider=provider.name,
            result=ProviderCallResult(ok=ok, error_category=category),
        )

    async def _release(self, organization_id: UUID, correlation_id: str) -> None:
        """Give the hold back. A ledger that will not answer is logged, never raised into the
        stream: the reservation is then stale rather than lost, and stale reservations are exactly
        what reconciliation exists to reclaim."""
        try:
            await self._reservation_service.release(
                organization_id=organization_id, correlation_id=correlation_id
            )
        except (LedgerUnavailableError, UnknownReservationError) as exc:
            _logger.error("stream_release_failed", reason=type(exc).__name__)

    async def _replayable(self, organization_id: UUID, key: CacheKey) -> str | None:
        """A cache hit this path can frame as chunks, or ``None`` for an ordinary miss."""
        try:
            cached = await self._cache.get(organization_id, key)
        except CacheUnavailableError:
            return None
        if cached is None or not isinstance(cached.content, str):
            return None
        return cached.content

    async def _safe_put(
        self, organization_id: UUID, key: CacheKey, response: CachedResponse
    ) -> None:
        try:
            await self._cache.put(organization_id, key, response)
        except CacheUnavailableError:
            return None


async def _replay(content: str) -> AsyncIterator[InferenceStreamEvent]:
    """Serve a cache hit as a single chunk (``docs/API_Streaming.md`` §1)."""
    yield StreamChunk(content=content)
