"""Money - deterministic monetary value (ADR-0016 Slice 8).

Shared by pricing, cost accounting and budget enforcement, so it lives in its own module rather
than being owned by any one of them (Rule 3): all three must agree on what an amount of money
*is*, and disagreement here would be silent - a currency-less float compared against another
currency-less float produces a number, not an error.

**Never a float.** Binary floating point cannot represent most decimal fractions exactly (0.1 is
already an infinite binary fraction); summing many such approximations - exactly what happens when
usage accumulates over many requests - drifts. ``Decimal`` is exact for the base-10 literals this
project's prices and costs are always expressed in.

**Rounding rule (established here, first use in the project):** amounts are quantized to 8
decimal places - matching ``docs/Schema.sql``'s `numeric(18,8)` columns for `price_table` and
`usage_ledger.cost_amount` - using ``ROUND_HALF_EVEN`` (banker's rounding). Half-even is the
deterministic, bias-free standard for repeated financial rounding: half-up systematically
inflates a long-run sum, which is precisely the kind of drift this type exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

CURRENCY_EXPONENT = Decimal("0.00000001")  # 8 decimal places, mirrors numeric(18,8)


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in one currency. Amounts in different currencies can never be combined."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"Money.amount must be a Decimal, got {type(self.amount).__name__} - "
                "a float here would reintroduce the drift this type exists to prevent"
            )
        if len(self.currency) != 3 or not self.currency.isupper() or not self.currency.isalpha():
            raise ValueError(
                f"currency must be a 3-letter uppercase ISO 4217 code, got {self.currency!r}"
            )

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError(
                f"cannot combine {self.currency} with {other.currency} - "
                "this project performs no currency conversion"
            )
        return Money(self.amount + other.amount, self.currency)

    def quantize(self) -> Money:
        """Round to the project's fixed 8-decimal-place rule (banker's rounding)."""
        rounded = self.amount.quantize(CURRENCY_EXPONENT, rounding=ROUND_HALF_EVEN)
        return Money(rounded, self.currency)
