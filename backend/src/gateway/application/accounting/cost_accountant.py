"""CostAccountant - converts provider-reported usage into deterministic monetary cost
(ADR-0016 Slice 8).

One job: ``usage x price -> CostRecord``. It does not decide whether a tenant can afford the
cost (``BudgetEnforcer``'s job), does not call a provider (``ProviderExecutor``'s job), does not
estimate cost before a call happens (``CostAgent``'s job, routing-time, unchanged by this slice),
and never touches ``RoutingDecision`` or ``RoutingExecution``.

Not itself a port: like ``ProviderExecutor`` and ``AgentRuntime``, this is a concrete orchestrator
built in the composition root, composing the real port (``PricingPort``) rather than being one.

## Failure semantics: configuration defects are exceptions, never budget denials

``MissingUsageError``, ``MalformedUsageError`` and ``UnknownPriceError`` are raised, not returned
as a ``CostRecord`` variant. Each signals something a *human* must fix (a client that lost track
of its own usage, a negative token count, a model with no price table entry) - none of them is a
fact about a tenant's spend, and folding them into the same return type as a budget decision would
let configuration corruption masquerade as an ordinary "no budget" denial (the same reasoning
``RoutingIntegrityError`` applies to a routing engine/catalog disagreement).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice, PricingPort
from gateway.application.ports.providers import ProviderResponse, ProviderUsage
from gateway.application.routing.catalog import ProviderDescriptor

_PER_THOUSAND = Decimal(1000)


def compute_cost(usage: ProviderUsage, price: ModelPrice) -> tuple[Money, Money, Money]:
    """``usage x price -> (input_cost, output_cost, total_cost)``, quantized once, shared by
    ``CostAccountant.account`` (actual usage) and ``ReservationService`` (Slice 9, estimated
    usage) - both must round the same way, or an estimate and its own settlement could
    disagree about a boundary amount (Rule 3: this is exactly a fact two modules must agree on,
    silently, if left as duplicated arithmetic)."""
    input_cost = Money(
        (Decimal(usage.prompt_tokens) / _PER_THOUSAND) * price.input_price_per_1k,
        price.currency,
    ).quantize()
    output_cost = Money(
        (Decimal(usage.completion_tokens) / _PER_THOUSAND) * price.output_price_per_1k,
        price.currency,
    ).quantize()
    total_cost = (input_cost + output_cost).quantize()
    return input_cost, output_cost, total_cost


class MissingUsageError(RuntimeError):
    """Accounting was requested for a response that reports no usage.

    Not a business outcome - a caller defect (accounting should only ever be invoked for a
    response where the provider actually incurred usage) or the expected shape of a provider
    failure that occurred before any tokens were consumed. Either way, there is nothing to
    account for, and fabricating a zero-cost record would misrepresent "we don't know" as
    "we know it cost nothing."
    """


class MalformedUsageError(ValueError):
    """Provider-reported usage contains a negative token count - a data integrity defect."""


class UnknownPriceError(RuntimeError):
    """No price is configured for this provider/model - a configuration defect, never a budget
    denial. An operator must add a price before this model can be accounted for."""


@dataclass(frozen=True, slots=True)
class CostRecord:
    """Deterministic actual cost of one provider call. Immutable, like ``RoutingDecision``."""

    organization_id: UUID
    correlation_id: str
    provider: str
    model: str
    usage: ProviderUsage
    input_cost: Money
    output_cost: Money
    total_cost: Money


class CostAccountant:
    """Turns provider-reported usage into a ``CostRecord``. Nothing more."""

    def __init__(self, pricing: PricingPort) -> None:
        self._pricing = pricing

    async def account(
        self,
        response: ProviderResponse,
        *,
        provider: ProviderDescriptor,
        organization_id: UUID,
        correlation_id: str,
    ) -> CostRecord:
        """Compute the actual cost of ``response``. Raises on anything that is not spend data."""
        if response.usage is None:
            raise MissingUsageError(
                f"cannot account correlation_id={correlation_id!r}: response carries no usage "
                "(provider failure before usage existed, or a caller defect)"
            )
        usage = response.usage
        if usage.prompt_tokens < 0 or usage.completion_tokens < 0:
            raise MalformedUsageError(
                f"negative token count for correlation_id={correlation_id!r}: {usage!r}"
            )

        price = await self._pricing.price_for(
            provider.name, provider.model, organization_id=organization_id
        )
        if price is None:
            raise UnknownPriceError(
                f"no price configured for provider={provider.name!r} model={provider.model!r}"
            )

        input_cost, output_cost, total_cost = compute_cost(usage, price)

        return CostRecord(
            organization_id=organization_id,
            correlation_id=correlation_id,
            provider=provider.name,
            model=provider.model,
            usage=usage,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
        )
