"""ReservationService tests (ADR-0016 Slice 9).

Exercises the full reserve -> execute -> settle/release sequence a caller must perform, against
the fast InMemoryBudgetLedger. Real atomicity/concurrency/RLS claims are proven separately against
PostgreSQL (tests/integration/test_budget_ledger_postgres.py) - this file proves the orchestration
and failure-semantics, not the database guarantee.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.in_memory_client import InMemoryProviderClient
from gateway.application.accounting.cost_accountant import (
    CostAccountant,
    MissingUsageError,
    UnknownPriceError,
)
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.ports.ledger import ReservationOutcome
from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import InferenceRequest, ProviderResponse
from gateway.application.routing.catalog import ProviderDescriptor

ORG = uuid4()
OPENAI = ProviderDescriptor(name="openai", model="gpt-4o")
PRICE = ModelPrice(
    provider="openai",
    model="gpt-4o",
    input_price_per_1k=Decimal("1"),
    output_price_per_1k=Decimal("2"),
    currency="USD",
)


def _service(
    ledger: InMemoryBudgetLedger, prices: tuple[ModelPrice, ...] = (PRICE,)
) -> ReservationService:
    pricing = StaticPriceTable(prices)
    return ReservationService(ledger, pricing, CostAccountant(pricing))


def _request(correlation_id: str, prompt: str = "hello") -> InferenceRequest:
    return InferenceRequest(correlation_id=correlation_id, payload={"prompt": prompt})


# ------------------------------------------------------------------ reserve


async def test_reserve_succeeds_within_budget() -> None:
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    service = _service(ledger)

    result = await service.reserve(organization_id=ORG, provider=OPENAI, request=_request("c1"))

    assert result.outcome is ReservationOutcome.RESERVED


async def test_reserve_denied_when_estimate_exceeds_budget() -> None:
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("0.000001"), "USD")})
    service = _service(ledger)

    result = await service.reserve(
        organization_id=ORG, provider=OPENAI, request=_request("c1", prompt="hello world " * 100)
    )

    assert result.outcome is ReservationOutcome.EXCEEDED
    assert result.permitted is False


async def test_reserve_unavailable_store_fails_closed_as_a_decision_not_an_exception() -> None:
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")}, unavailable=True)
    service = _service(ledger)

    result = await service.reserve(organization_id=ORG, provider=OPENAI, request=_request("c1"))

    assert result.outcome is ReservationOutcome.UNAVAILABLE
    assert result.permitted is False


async def test_reserve_raises_for_an_unpriced_model_a_configuration_defect() -> None:
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    service = _service(ledger, prices=())

    with pytest.raises(UnknownPriceError):
        await service.reserve(organization_id=ORG, provider=OPENAI, request=_request("c1"))


# ------------------------------------------------------------------ full reserve/execute/settle


async def test_full_sequence_reserve_execute_settle() -> None:
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    service = _service(ledger)
    request = _request("c1")

    reservation = await service.reserve(organization_id=ORG, provider=OPENAI, request=request)
    assert reservation.permitted is True

    response = await InMemoryProviderClient().invoke(OPENAI, request)
    record = await service.settle(
        organization_id=ORG, correlation_id="c1", response=response, provider=OPENAI
    )

    assert record.total_cost.amount >= 0
    # The reservation's slack (estimate was conservative) is now free for a new request.
    result = await ledger.reserve(ORG, "c2", Money(Decimal("999"), "USD"))
    assert result.outcome is ReservationOutcome.RESERVED


async def test_settle_propagates_missing_usage_and_leaves_the_reservation_held() -> None:
    """A provider failure before usage exists must not be settled as zero-cost - the reservation
    stays held so the caller can release() it instead (see test below)."""
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("1000"), "USD")})
    service = _service(ledger)
    request = _request("c1")
    await service.reserve(organization_id=ORG, provider=OPENAI, request=request)
    failed_response = ProviderResponse(ok=False, error="boom", provider="openai")

    with pytest.raises(MissingUsageError):
        await service.settle(
            organization_id=ORG, correlation_id="c1", response=failed_response, provider=OPENAI
        )


async def test_release_frees_a_reservation_after_a_failed_provider_call() -> None:
    ledger = InMemoryBudgetLedger({ORG: Money(Decimal("100"), "USD")})
    service = _service(ledger)
    await service.reserve(organization_id=ORG, provider=OPENAI, request=_request("c1", "x" * 400))

    await service.release(organization_id=ORG, correlation_id="c1")

    # Full budget is available again - a second reservation of the whole limit now fits.
    result = await ledger.reserve(ORG, "c2", Money(Decimal("100"), "USD"))
    assert result.outcome is ReservationOutcome.RESERVED
