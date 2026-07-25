"""Static, in-memory PricingPort (ADR-0016 Slice 8, Rule 4; Rule 5 signature update Slice 19).

No live pricing API and no effective-dated versioning - that is ``SqlPriceTable``'s job as of
Slice 19. Prices are seeded at construction and never change at runtime. This remains the
implementation a deployment without PostgreSQL gets, and the second implementation that keeps the
port honest.

## Why this one ignores ``organization_id``

Slice 19 added the tenant to ``price_for`` because ``price_table`` is tenant-scoped and cannot be
read without it. This table is not that table: it is a single deployment-level price list, so
every tenant sees the same prices, and silently returning nothing for an organization it has never
heard of would be worse than useless - it would turn "no negotiated rate" into ``UnknownPriceError``
for every caller. Ignoring the argument is therefore the correct behaviour here, and it is stated
rather than left for a reader to infer from an unused parameter.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from gateway.application.ports.pricing import ModelPrice, PricingPort


class StaticPriceTable(PricingPort):
    """Deployment-wide price list, keyed by (provider, model)."""

    def __init__(self, prices: Iterable[ModelPrice] = ()) -> None:
        self._prices: dict[tuple[str, str], ModelPrice] = {
            (price.provider, price.model): price for price in prices
        }

    async def price_for(
        self, provider: str, model: str, *, organization_id: UUID
    ) -> ModelPrice | None:
        """The same price for every tenant - see the module docstring on ``organization_id``."""
        return self._prices.get((provider, model))
