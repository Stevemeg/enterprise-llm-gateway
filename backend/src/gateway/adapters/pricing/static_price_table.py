"""Static, in-memory PricingPort (ADR-0016 Slice 8, Rule 4).

No live pricing API, no historical/effective-dated versioning (``docs/Schema.sql``'s
`price_table.effective_from/to` is future work with no consumer here). Prices are seeded at
construction and never change at runtime. This is deliberately the only implementation this
slice ships - "a deterministic in-memory/static pricing implementation is sufficient" - so no
independence contract exists between pricing adapters; there is nothing yet to be independent
from (recorded, not hidden, in the evidence log).
"""

from __future__ import annotations

from collections.abc import Iterable

from gateway.application.ports.pricing import ModelPrice, PricingPort


class StaticPriceTable(PricingPort):
    """Global (not tenant-scoped) price list, keyed by (provider, model)."""

    def __init__(self, prices: Iterable[ModelPrice] = ()) -> None:
        self._prices: dict[tuple[str, str], ModelPrice] = {
            (price.provider, price.model): price for price in prices
        }

    async def price_for(self, provider: str, model: str) -> ModelPrice | None:
        return self._prices.get((provider, model))
