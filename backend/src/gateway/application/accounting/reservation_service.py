"""ReservationService - sequences reserve -> execute -> settle/release (ADR-0016 Slice 9).

The piece Slice 8 explicitly could not provide: a check that runs *before* ``ProviderExecutor``
is invoked, so a rejected reservation means the provider is never called - not merely that
already-incurred spend gets classified afterwards (``BudgetEnforcer``'s job, unchanged, still
valid for its own purpose).

Not itself a port: like ``ProviderExecutor`` and ``CostAccountant``, this is a concrete
orchestrator built in the composition root, composing real ports (``BudgetLedgerPort``,
``PricingPort``) and the existing ``CostAccountant`` rather than being one.

## Responsibility boundary

This class does not call a provider (``ProviderExecutor``'s job) and does not compute cost from
provider-reported usage itself (``CostAccountant``'s job, reused unchanged for the *actual* side of
settlement). It only decides "may this proceed" before the call and "release the hold" after -
the sequencing a caller (a future delivery-layer handler; today, tests and the container wiring
that prove the seam per Rule 4) must perform is: ``reserve`` -> only if permitted, call
``ProviderExecutor.execute`` -> ``settle`` on a response with usage, or ``release`` if the provider
call failed before usage existed.
"""

from __future__ import annotations

from uuid import UUID

from gateway.application.accounting.cost_accountant import (
    CostAccountant,
    CostRecord,
    UnknownPriceError,
    compute_cost,
)
from gateway.application.accounting.estimator import estimate_usage
from gateway.application.ports.ledger import (
    BudgetLedgerPort,
    LedgerUnavailableError,
    ReservationOutcome,
    ReservationResult,
    SettlementDetail,
)
from gateway.application.ports.pricing import PricingPort
from gateway.application.ports.providers import InferenceRequest, ProviderResponse
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.metrics import record_budget_reservation


class ReservationService:
    """Gates a provider call against a budget, then settles or releases the hold."""

    def __init__(
        self, ledger: BudgetLedgerPort, pricing: PricingPort, cost_accountant: CostAccountant
    ) -> None:
        self._ledger = ledger
        self._pricing = pricing
        self._cost_accountant = cost_accountant

    async def reserve(
        self, *, organization_id: UUID, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ReservationResult:
        """Estimate the call's cost and atomically hold it against the org's budget.

        Never raises for a ledger outage - fails closed (ADR-0009 row 1), mirroring
        ``BudgetEnforcer.evaluate``. Raises ``UnknownPriceError`` for an unpriced model - a
        configuration defect, never a budget denial (same reasoning as ``CostAccountant``).
        """
        price = await self._pricing.price_for(provider.name, provider.model)
        if price is None:
            raise UnknownPriceError(
                f"no price configured for provider={provider.name!r} model={provider.model!r}"
            )
        estimate = estimate_usage(request)
        _, _, estimated_cost = compute_cost(estimate, price)
        try:
            result = await self._ledger.reserve(
                organization_id, request.correlation_id, estimated_cost
            )
        except LedgerUnavailableError:
            result = ReservationResult(
                outcome=ReservationOutcome.UNAVAILABLE,
                organization_id=organization_id,
                correlation_id=request.correlation_id,
                estimated_cost=estimated_cost,
            )
        # Slice 16: this component owns the budget gate, so it reports the verdict. A ledger
        # outage is visible as its own outcome rather than being folded into a denial - they are
        # different operational facts (ADR-0009 row 1).
        record_budget_reservation(outcome=result.outcome.value)
        return result

    async def settle(
        self,
        *,
        organization_id: UUID,
        correlation_id: str,
        response: ProviderResponse,
        provider: ProviderDescriptor,
    ) -> CostRecord:
        """Compute actual cost from ``response`` and release the reservation as committed spend.

        Raises whatever ``CostAccountant.account`` raises for a response with no/malformed usage
        or an unpriced model - none of those are settled (the reservation is left ``reserved``
        for the caller to ``release`` or retry, not silently written off).
        """
        record = await self._cost_accountant.account(
            response,
            provider=provider,
            organization_id=organization_id,
            correlation_id=correlation_id,
        )
        detail = SettlementDetail(
            provider=record.provider,
            model=record.model,
            prompt_tokens=record.usage.prompt_tokens,
            completion_tokens=record.usage.completion_tokens,
            input_cost=record.input_cost,
            output_cost=record.output_cost,
            total_cost=record.total_cost,
        )
        await self._ledger.settle(organization_id, correlation_id, detail)
        return record

    async def release(self, *, organization_id: UUID, correlation_id: str) -> None:
        """Release a reservation's hold without recording spend (no usage was incurred)."""
        await self._ledger.release(organization_id, correlation_id)
