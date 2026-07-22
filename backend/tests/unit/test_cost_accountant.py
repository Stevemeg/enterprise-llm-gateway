"""CostAccountant tests (ADR-0016 Slice 8).

Fail-safe paths first: distinguishing a configuration defect (unknown price, malformed usage,
missing usage) from ordinary zero-cost data is the accountant's most important behaviour.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.application.accounting.cost_accountant import (
    CostAccountant,
    MalformedUsageError,
    MissingUsageError,
    UnknownPriceError,
)
from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import ProviderResponse, ProviderUsage
from gateway.application.routing.catalog import ProviderDescriptor

ORG = uuid4()
OPENAI = ProviderDescriptor(name="openai", model="gpt-4o")

PRICE = ModelPrice(
    provider="openai",
    model="gpt-4o",
    input_price_per_1k=Decimal("2.50"),
    output_price_per_1k=Decimal("10.00"),
    currency="USD",
)


def _accountant(*prices: ModelPrice) -> CostAccountant:
    return CostAccountant(StaticPriceTable(prices))


def _response(prompt: int, completion: int, *, ok: bool = True) -> ProviderResponse:
    return ProviderResponse(
        ok=ok,
        provider="openai",
        usage=ProviderUsage(prompt_tokens=prompt, completion_tokens=completion),
    )


# ------------------------------------------------------------------ fail-safe paths first


async def test_missing_usage_raises_rather_than_fabricating_a_cost() -> None:
    """Provider failure before usage exists must not produce a fabricated zero-cost record."""
    response = ProviderResponse(ok=False, provider="openai", usage=None)

    with pytest.raises(MissingUsageError):
        await _accountant(PRICE).account(
            response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
        )


@pytest.mark.parametrize(("prompt", "completion"), [(-1, 0), (0, -1), (-5, -5)])
async def test_negative_token_counts_are_rejected(prompt: int, completion: int) -> None:
    response = _response(prompt, completion)

    with pytest.raises(MalformedUsageError):
        await _accountant(PRICE).account(
            response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
        )


async def test_unknown_price_raises_rather_than_denying_a_budget() -> None:
    """An unpriced model is a configuration defect, never a budget outcome."""
    response = _response(100, 50)

    with pytest.raises(UnknownPriceError):
        await _accountant().account(  # no prices configured at all
            response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
        )


# ------------------------------------------------------------------ deterministic cost


async def test_deterministic_input_and_output_cost() -> None:
    response = _response(1234, 567)

    record = await _accountant(PRICE).account(
        response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
    )

    # 1234/1000 * 2.50 = 3.085 ; 567/1000 * 10.00 = 5.67 ; both exact in Decimal.
    assert record.input_cost == Money(Decimal("3.08500000"), "USD")
    assert record.output_cost == Money(Decimal("5.67000000"), "USD")


async def test_combined_cost_is_input_plus_output() -> None:
    response = _response(1234, 567)

    record = await _accountant(PRICE).account(
        response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
    )

    assert record.total_cost == Money(Decimal("8.75500000"), "USD")
    assert record.total_cost == record.input_cost + record.output_cost


async def test_zero_usage_is_valid_and_costs_nothing() -> None:
    """Zero usage is real data (a trivially short call), not a defect."""
    response = _response(0, 0)

    record = await _accountant(PRICE).account(
        response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
    )

    assert record.total_cost == Money(Decimal("0.00000000"), "USD")


async def test_zero_price_is_valid_and_costs_nothing() -> None:
    """A deliberately free model must cost zero, not be indistinguishable from unpriced."""
    free = ModelPrice(
        provider="openai",
        model="gpt-4o",
        input_price_per_1k=Decimal("0"),
        output_price_per_1k=Decimal("0"),
        currency="USD",
    )
    response = _response(1000, 1000)

    record = await _accountant(free).account(
        response, provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
    )

    assert record.total_cost == Money(Decimal("0.00000000"), "USD")


async def test_fractional_token_pricing_accumulates_without_drift() -> None:
    """The realistic manifestation of float drift is accumulation over many calls, not a single
    computation - this is the case that would actually surface a bug in production."""
    fractional = ModelPrice(
        provider="openai",
        model="gpt-4o",
        input_price_per_1k=Decimal("0.1"),
        output_price_per_1k=Decimal("0"),
        currency="USD",
    )
    accountant = _accountant(fractional)
    response = _response(1, 0)  # 1/1000 * 0.1 = 0.0001, well-behaved in float too in isolation

    records = [
        await accountant.account(
            response, provider=OPENAI, organization_id=ORG, correlation_id=f"corr-{i}"
        )
        for i in range(3)
    ]

    total = records[0].total_cost
    for record in records[1:]:
        total = total + record.total_cost

    assert total == Money(Decimal("0.00030000"), "USD")


# ------------------------------------------------------------------ CostRecord identity


async def test_cost_record_is_immutable() -> None:
    import dataclasses

    record = await _accountant(PRICE).account(
        _response(10, 5), provider=OPENAI, organization_id=ORG, correlation_id="corr-1"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.total_cost = Money(Decimal("0"), "USD")  # type: ignore[misc]
