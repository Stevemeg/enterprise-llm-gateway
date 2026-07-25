"""Durable, tenant-scoped, effective-dated ``PricingPort`` backed by PostgreSQL (Slice 19).

Realizes what ``StaticPriceTable``'s docstring deferred: "no historical/effective-dated versioning
(``docs/Schema.sql``'s `price_table.effective_from/to` is future work with no consumer here)".
Slice 19 is that consumer, because a durable price list is only trustworthy if a settled cost can
be reproduced against the price that was in force when the call happened (FR-074/075, SM-T07).

## Why the row is chosen by time rather than by "the latest"

``effective_from <= now < effective_to`` (with ``NULL`` meaning "still current") selects the price
that is in force. Taking ``ORDER BY effective_from DESC LIMIT 1`` alone would quietly apply a
*future* price the moment an operator scheduled one - a rise entered on Monday to take effect next
month would start charging immediately. The clock is injected so this is testable rather than a
fact about the machine the test happens to run on.

## Scope, and what deliberately is not here

One price per (provider, model, tenant, instant). Overlapping rows for the same instant are a
configuration defect that the database's ``price_model_effective_key`` and ``price_effective_ck``
constraints already narrow; this adapter orders by ``effective_from DESC`` and takes one, so a
defect yields the most recently-effective price rather than an arbitrary one. It does not merge,
average, or fall back to a global price list: an unpriced model must surface as
``UnknownPriceError`` at the caller, never as a guess.

The table modules are imported under ``_table`` aliases because ``provider`` and ``model`` are also
the port's parameter names, and the port's names must not change - a ``Protocol`` is matched by
parameter name, so renaming them here would silently stop this class satisfying ``PricingPort``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from gateway.adapters.persistence.catalog_tables import model as model_table
from gateway.adapters.persistence.catalog_tables import price_table
from gateway.adapters.persistence.catalog_tables import provider as provider_table
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.ports.pricing import ModelPrice, PricingPort
from gateway.observability.logging import get_logger
from gateway.shared.clock import Clock

_logger = get_logger("pricing")


class PriceTableUnavailableError(RuntimeError):
    """The price list could not be read - distinct from "this model has no price"."""


class SqlPriceTable(PricingPort):
    """Resolves the price in force for one provider/model within one tenant."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def price_for(
        self, provider: str, model: str, *, organization_id: UUID
    ) -> ModelPrice | None:
        now = self._clock.now()
        query = (
            select(
                price_table.c.input_price_per_1k,
                price_table.c.output_price_per_1k,
                price_table.c.currency,
            )
            .select_from(
                price_table.join(model_table, model_table.c.id == price_table.c.model_id).join(
                    provider_table, provider_table.c.id == model_table.c.provider_id
                )
            )
            .where(
                price_table.c.organization_id == organization_id,
                provider_table.c.name == provider,
                model_table.c.name == model,
                price_table.c.effective_from <= now,
                or_(price_table.c.effective_to.is_(None), price_table.c.effective_to > now),
            )
            .order_by(price_table.c.effective_from.desc())
            .limit(1)
        )
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                row = (await uow.session.execute(query)).mappings().first()
        except (SQLAlchemyError, OSError) as exc:
            # Returning None here would become UnknownPriceError - "an operator must add a price" -
            # for what is actually an outage. Raising keeps the two apart. Only the exception TYPE
            # is logged; SQLAlchemy messages can quote bound parameters (NFR-SEC03).
            _logger.error("price_lookup_failed", error=type(exc).__name__)
            raise PriceTableUnavailableError(type(exc).__name__) from exc

        if row is None:
            return None
        return ModelPrice(
            provider=provider,
            model=model,
            input_price_per_1k=row["input_price_per_1k"],
            output_price_per_1k=row["output_price_per_1k"],
            currency=row["currency"],
        )
