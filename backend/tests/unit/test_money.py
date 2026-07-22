"""Money tests (ADR-0016 Slice 8).

The type exists to prevent float drift; the tests exist to prove it actually does, not merely to
exercise the dataclass.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from gateway.application.ports.money import Money


def test_float_amount_is_rejected() -> None:
    """A float here would silently reintroduce the drift this type exists to prevent."""
    with pytest.raises(TypeError):
        Money(0.1, "USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("currency", ["us", "USDD", "US1", "usd"])
def test_malformed_currency_code_is_rejected(currency: str) -> None:
    with pytest.raises(ValueError, match="ISO 4217"):
        Money(Decimal("1"), currency)


def test_adding_mismatched_currencies_raises() -> None:
    with pytest.raises(ValueError, match="cannot combine"):
        Money(Decimal("1"), "USD") + Money(Decimal("1"), "EUR")


def test_decimal_summation_avoids_float_drift() -> None:
    """The canonical case: 0.1 + 0.1 + 0.1 != 0.3 in binary float, but is exact in Decimal."""
    assert 0.1 + 0.1 + 0.1 != 0.3  # the drift this type exists to prevent

    total = (
        Money(Decimal("0.1"), "USD") + Money(Decimal("0.1"), "USD") + Money(Decimal("0.1"), "USD")
    )

    assert total == Money(Decimal("0.3"), "USD")


def test_quantize_rounds_half_to_even() -> None:
    """The project's explicit, first-established rounding rule: 8 decimal places, banker's
    rounding. 1.234567895 sits exactly halfway at the 9th place; the preceding digit (9) is odd,
    so half-even rounds it up to the nearest even digit (0), not down."""
    amount = Money(Decimal("1.234567895"), "USD")

    assert amount.quantize() == Money(Decimal("1.23456790"), "USD")


def test_quantize_of_an_already_exact_amount_is_unchanged() -> None:
    exact = Money(Decimal("3.08500000"), "USD")
    assert exact.quantize() == exact
