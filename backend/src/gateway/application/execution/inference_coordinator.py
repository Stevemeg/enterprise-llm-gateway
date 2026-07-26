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

## Phase 5 M2: an unaccountable call is a refusal, not a crash

``CostAccountant``'s ``UnknownPriceError``/``MissingUsageError``/``MalformedUsageError`` are still
raised where they are raised, and they still mean "a human must fix something" - none of that
changes. What changed is that they used to *escape this class entirely*, propagate through
reflection and serving untouched, and arrive at the HTTP layer as an unhandled exception: a
**generic 500** for what is actually a deliberate fail-closed refusal, with the budget hold left
reserved behind it because nobody released it.

They are now caught here, at the only place that both knows the reservation exists and owns the
outcome vocabulary, and turned into ``ExecutionOutcome.NOT_ACCOUNTABLE``:

* **before the call** (unpriced model at ``reserve``) - nothing was held and no provider was
  called, so there is nothing to undo;
* **after the call** (``settle`` cannot compute a cost) - the hold is **released**, because the
  alternative is charging an amount nobody could compute, and leaving it reserved is the leak M2's
  reconciliation exists to clean up rather than a thing to keep creating.

The exception type never reaches the caller; it goes to the log for the operator, and the metric
records the outcome. Reflection treats the new outcome as terminal without any change of its own
(``classify`` already terminates every non-``EXECUTED`` outcome) - retrying a configuration defect
is precisely wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from gateway.application.accounting.cost_accountant import (
    CostRecord,
    MalformedUsageError,
    MissingUsageError,
    UnknownPriceError,
)
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.ports.cache import (
    CachedResponse,
    CacheKey,
    CacheUnavailableError,
    ResponseCachePort,
)
from gateway.application.ports.circuit_breaker import CircuitBreaker, ProviderCallResult
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.ledger import ReservationOutcome
from gateway.application.ports.providers import InferenceRequest, ProviderResponse
from gateway.application.ports.routing import RoutingExecution
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.logging import get_logger
from gateway.observability.metrics import record_cache_lookup, record_inference_attempt

_logger = get_logger("execution")

#: Everything ``CostAccountant`` raises when a call cannot be turned into money. Named once, so
#: the pre-call and post-call handlers cannot drift apart about what "unaccountable" means.
ACCOUNTING_DEFECTS = (UnknownPriceError, MissingUsageError, MalformedUsageError)

#: The only text a caller may see for this outcome. Says nothing about prices, models or usage:
#: the operator gets the detail from the log line, the caller gets a stable token.
NOT_ACCOUNTABLE_ERROR = "not_accountable"


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
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._cache = cache
        self._deduplicator = deduplicator
        self._reservation_service = reservation_service
        self._provider_executor = provider_executor
        self._circuit_breaker = circuit_breaker

    async def execute(
        self, execution: RoutingExecution, request: InferenceRequest
    ) -> InferenceExecutionResult:
        if not execution.routed or execution.provider is None:
            response = await self._provider_executor.execute(execution, request)
            record_inference_attempt(outcome=ExecutionOutcome.NOT_ROUTED.value)
            return InferenceExecutionResult(outcome=ExecutionOutcome.NOT_ROUTED, response=response)

        organization_id = execution.decision.organization_id
        provider = execution.provider
        key = compute_cache_key(
            organization_id, provider=provider.name, model=provider.model, payload=request.payload
        )

        cached = await self._safe_get(organization_id, key)
        # Slice 16: this component owns the cache decision, so hit rate is reported here. A
        # cache *outage* is a miss for this purpose - the request proceeds either way, and
        # ``_safe_get`` has already converted the failure into "no entry".
        record_cache_lookup(hit=cached is not None)
        if cached is not None:
            response = ProviderResponse(
                ok=True, content=cached.content, provider=cached.provider, usage=None
            )
            record_inference_attempt(outcome=ExecutionOutcome.CACHE_HIT.value)
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

        try:
            reservation = await self._reservation_service.reserve(
                organization_id=organization_id, provider=provider, request=request
            )
        except ACCOUNTING_DEFECTS as exc:
            # Nothing was held and no provider was called, so there is nothing to undo - the
            # request simply is not servable until an operator adds the missing price.
            return self._not_accountable(phase="reserve", provider=provider, exc=exc)
        if not reservation.permitted:
            outcome = (
                ExecutionOutcome.BUDGET_UNAVAILABLE
                if reservation.outcome is ReservationOutcome.UNAVAILABLE
                else ExecutionOutcome.BUDGET_DENIED
            )
            response = ProviderResponse(ok=False, error=f"budget_{reservation.outcome.value}")
            record_inference_attempt(outcome=outcome.value)
            return InferenceExecutionResult(outcome=outcome, response=response)

        response = await self._provider_executor.execute(execution, request)
        # Slice 20: a *real* provider call happened, so feed its outcome to the circuit breaker.
        # This is the only place that observes health: cache hits, budget denials and unrouted
        # requests never reach here, so a circuit only ever moves on evidence of an actual call.
        # The breaker itself decides what counts (success closes, transient fault opens, client
        # errors are ignored) - the coordinator just reports what happened.
        self._circuit_breaker.observe(
            organization_id=organization_id,
            provider=provider.name,
            result=ProviderCallResult(ok=response.ok, error_category=response.error_category),
        )
        if not response.ok:
            await self._reservation_service.release(
                organization_id=organization_id, correlation_id=request.correlation_id
            )
            record_inference_attempt(outcome=ExecutionOutcome.EXECUTED.value)
            return InferenceExecutionResult(outcome=ExecutionOutcome.EXECUTED, response=response)

        try:
            record = await self._reservation_service.settle(
                organization_id=organization_id,
                correlation_id=request.correlation_id,
                response=response,
                provider=provider,
            )
        except ACCOUNTING_DEFECTS as exc:
            # The provider ran but its call cannot be costed. Release rather than leave the hold
            # reserved: an amount nobody can compute must not be charged, and a hold nobody
            # releases is the leak reconciliation exists to clean up, not one to keep creating.
            await self._reservation_service.release(
                organization_id=organization_id, correlation_id=request.correlation_id
            )
            return self._not_accountable(phase="settle", provider=provider, exc=exc)
        await self._safe_put(
            organization_id,
            key,
            CachedResponse(
                provider=response.provider, model=provider.model, content=response.content
            ),
        )
        record_inference_attempt(outcome=ExecutionOutcome.EXECUTED.value)
        return InferenceExecutionResult(
            outcome=ExecutionOutcome.EXECUTED, response=response, cost=record
        )

    @staticmethod
    def _not_accountable(
        *, phase: str, provider: ProviderDescriptor, exc: Exception
    ) -> InferenceExecutionResult:
        """One exit for both accounting-defect paths, so neither can leak what the other hides.

        ``phase`` and the exception's *type* go to the operator's log; the caller receives a bare
        outcome and a fixed token. A price-table gap is deployment configuration, and naming it in
        a response would tell an untrusted caller which models this deployment cannot price.
        """
        _logger.error(
            "inference_not_accountable",
            phase=phase,
            provider=provider.name,
            model=provider.model,
            reason=type(exc).__name__,
        )
        record_inference_attempt(outcome=ExecutionOutcome.NOT_ACCOUNTABLE.value)
        return InferenceExecutionResult(
            outcome=ExecutionOutcome.NOT_ACCOUNTABLE,
            response=ProviderResponse(ok=False, error=NOT_ACCOUNTABLE_ERROR),
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
