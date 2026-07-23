"""InferenceCoordinator - layers caching and request deduplication around the existing
reserve -> execute -> settle/release sequence (ADR-0016 Slice 10).

Composes, and adds no intelligence to, four already-independent capabilities:

* ``ResponseCachePort``    - exact-match cache lookup/store (this slice).
* ``RequestDeduplicator``  - process-local in-flight coalescing (this slice).
* ``ReservationService``   - budget gate (Slice 9); unchanged, still the only budget authority.
* ``ProviderExecutor``     - the only thing that calls a provider (Slice 7); unchanged.

This is the "future delivery-layer handler" both ``ReservationService`` and ``ProviderExecutor``'s
own docstrings anticipate - the first real caller that performs the full sequence end to end, not a
fifth decision-maker. It does not decide routing (``execution: RoutingExecution`` arrives already
decided by ``AgentRuntime``/``RoutingEngine``), does not compute cost itself (delegates to
``ReservationService``/``CostAccountant``), does not gate budget itself (delegates to
``ReservationService``), and does not call a provider itself (delegates to ``ProviderExecutor``).

## Where a cache lookup sits in the execution path, and why that is safe

Authorization has already run (a ``PipelineStage``, upstream of anything this class touches - this
package never imports the authorization seam at all, so it structurally cannot bypass it: there is
nothing here *to* bypass). Routing has already run and selected a provider, or not - an unrouted
``RoutingExecution`` is delegated straight to ``ProviderExecutor`` unchanged, and neither cache nor
dedup applies to a request nothing was ever going to execute. Only once both of those are settled
does a cache lookup happen, and only then because a hit requires knowing the tenant and the
resolved provider/model - exactly what routing decided, nothing this class invents itself.

## Hit vs. miss semantics (Rule 3 - explicit, not implied)

A cache hit is **not** provider execution. It creates no ``ProviderUsage`` (none was observed -
fabricating usage that was never incurred would misrepresent an observation that never happened,
the same discipline ``CostAccountant.MissingUsageError`` already applies for a different reason),
incurs no cost, and never reserves or settles budget: there is nothing to gate, because nothing
will be spent. A cache miss changes nothing about the pre-existing budget/execution/accounting
sequence - it is exactly the sequence that existed before this slice, unchanged, with the fresh
response stored afterward only if the call actually succeeded.

## Deduplication only wraps the miss path

A hit is a pure read with no side effects - concurrent duplicate callers can each read the cache
independently and get the same answer, so nothing needs coalescing there. Only a miss has side
effects (a budget reservation, a provider call, a settlement, a cache write), so only the miss path
is wrapped in ``RequestDeduplicator.coalesce``, keyed on ``(organization_id,
request.correlation_id)`` - never on the cache key, which is a different identity for a different
purpose (see ``deduplicator.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from gateway.application.accounting.cost_accountant import CostRecord
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.ports.cache import (
    CachedResponse,
    CacheKey,
    CacheUnavailableError,
    ResponseCachePort,
)
from gateway.application.ports.ledger import ReservationOutcome
from gateway.application.ports.providers import InferenceRequest, ProviderResponse
from gateway.application.ports.routing import RoutingExecution
from gateway.application.providers.provider_executor import ProviderExecutor


class ExecutionOutcome(StrEnum):
    """Closed vocabulary for how one coordinated execution ended (safe as a metric label,
    mirrors ``RoutingOutcome``)."""

    CACHE_HIT = "cache_hit"
    EXECUTED = "executed"
    NOT_ROUTED = "not_routed"
    BUDGET_DENIED = "budget_denied"
    BUDGET_UNAVAILABLE = "budget_unavailable"


@dataclass(frozen=True, slots=True)
class InferenceExecutionResult:
    """The coordinator's output. ``cost`` is populated only for ``EXECUTED`` with a successful
    provider response - never for a hit (nothing was spent) and never for a denial (nothing ran)."""

    outcome: ExecutionOutcome
    response: ProviderResponse
    cost: CostRecord | None = None


class InferenceCoordinator:
    """Serves a cache hit directly; otherwise deduplicates and runs reserve/execute/settle."""

    def __init__(
        self,
        cache: ResponseCachePort,
        deduplicator: RequestDeduplicator,
        reservation_service: ReservationService,
        provider_executor: ProviderExecutor,
    ) -> None:
        self._cache = cache
        self._deduplicator = deduplicator
        self._reservation_service = reservation_service
        self._provider_executor = provider_executor

    async def execute(
        self, execution: RoutingExecution, request: InferenceRequest
    ) -> InferenceExecutionResult:
        if not execution.routed or execution.provider is None:
            response = await self._provider_executor.execute(execution, request)
            return InferenceExecutionResult(outcome=ExecutionOutcome.NOT_ROUTED, response=response)

        organization_id = execution.decision.organization_id
        provider = execution.provider
        key = compute_cache_key(
            organization_id, provider=provider.name, model=provider.model, payload=request.payload
        )

        cached = await self._safe_get(organization_id, key)
        if cached is not None:
            response = ProviderResponse(
                ok=True, content=cached.content, provider=cached.provider, usage=None
            )
            return InferenceExecutionResult(outcome=ExecutionOutcome.CACHE_HIT, response=response)

        return await self._deduplicator.coalesce(
            organization_id,
            request.correlation_id,
            lambda: self._execute_and_settle(execution, request, key),
        )

    async def _execute_and_settle(
        self, execution: RoutingExecution, request: InferenceRequest, key: CacheKey
    ) -> InferenceExecutionResult:
        organization_id = execution.decision.organization_id
        provider = execution.provider
        if provider is None:  # pragma: no cover - guarded by the caller before scheduling
            raise AssertionError("_execute_and_settle requires a routed execution")

        reservation = await self._reservation_service.reserve(
            organization_id=organization_id, provider=provider, request=request
        )
        if not reservation.permitted:
            outcome = (
                ExecutionOutcome.BUDGET_UNAVAILABLE
                if reservation.outcome is ReservationOutcome.UNAVAILABLE
                else ExecutionOutcome.BUDGET_DENIED
            )
            response = ProviderResponse(ok=False, error=f"budget_{reservation.outcome.value}")
            return InferenceExecutionResult(outcome=outcome, response=response)

        response = await self._provider_executor.execute(execution, request)
        if not response.ok:
            await self._reservation_service.release(
                organization_id=organization_id, correlation_id=request.correlation_id
            )
            return InferenceExecutionResult(outcome=ExecutionOutcome.EXECUTED, response=response)

        record = await self._reservation_service.settle(
            organization_id=organization_id,
            correlation_id=request.correlation_id,
            response=response,
            provider=provider,
        )
        await self._safe_put(
            organization_id,
            key,
            CachedResponse(
                provider=response.provider, model=provider.model, content=response.content
            ),
        )
        return InferenceExecutionResult(
            outcome=ExecutionOutcome.EXECUTED, response=response, cost=record
        )

    async def _safe_get(self, organization_id: UUID, key: CacheKey) -> CachedResponse | None:
        try:
            return await self._cache.get(organization_id, key)
        except CacheUnavailableError:
            return None

    async def _safe_put(
        self, organization_id: UUID, key: CacheKey, response: CachedResponse
    ) -> None:
        try:
            await self._cache.put(organization_id, key, response)
        except CacheUnavailableError:
            return None
