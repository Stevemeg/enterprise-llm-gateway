"""Durable, effective-dated pricing against real PostgreSQL (FR-074/075, Slice 19).

Runs as ``app_rw`` (ADR-0014). The point of the effective-dating tests is reproducibility: a
settled cost must be computed against the price that was in force when the call happened, not
against whatever is newest.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.adapters.pricing.sql_price_table import PriceTableUnavailableError, SqlPriceTable
from tests.support.catalog import seed_model, seed_price, seed_provider
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]

_JAN = datetime(2026, 1, 1, tzinfo=UTC)
_JUN = datetime(2026, 6, 1, tzinfo=UTC)
_DEC = datetime(2026, 12, 1, tzinfo=UTC)


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)


async def _priced_model(factory: UnitOfWorkFactory, org: UUID) -> UUID:
    """Seed a provider + model and return the model id (still unpriced)."""
    provider_id = await seed_provider(factory, org, name="openai")
    return await seed_model(factory, org, provider_id, name="gpt-4o")


# ------------------------------------------------------------------ unpriced / isolation


async def test_an_unpriced_model_returns_none(factory: UnitOfWorkFactory) -> None:
    """None is not zero: the caller must turn it into UnknownPriceError, never free service."""
    org = uuid4()
    await seed_organization(factory, org)
    await _priced_model(factory, org)  # model exists, but no price row
    price = await SqlPriceTable(factory, FixedClock(_JUN)).price_for(
        "openai", "gpt-4o", organization_id=org
    )
    assert price is None


async def test_one_tenants_prices_are_invisible_to_another(factory: UnitOfWorkFactory) -> None:
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        await seed_organization(factory, org)
    model_a = await _priced_model(factory, org_a)
    await seed_price(
        factory, org_a, model_a, input_per_1k="1.00", output_per_1k="2.00", effective_from=_JAN
    )
    table = SqlPriceTable(factory, FixedClock(_JUN))
    assert await table.price_for("openai", "gpt-4o", organization_id=org_a) is not None
    assert await table.price_for("openai", "gpt-4o", organization_id=org_b) is None


# ------------------------------------------------------------------ effective dating


async def test_the_price_in_force_is_selected_by_time_not_by_newest(
    factory: UnitOfWorkFactory,
) -> None:
    """Two rows: an old one that has ended, and a current one. Only the row whose window contains
    ``now`` may be returned, whichever was inserted last."""
    org = uuid4()
    await seed_organization(factory, org)
    model_id = await _priced_model(factory, org)
    await seed_price(
        factory,
        org,
        model_id,
        input_per_1k="1.00",
        output_per_1k="1.00",
        effective_from=_JAN,
        effective_to=_JUN,
    )
    await seed_price(
        factory, org, model_id, input_per_1k="3.00", output_per_1k="3.00", effective_from=_JUN
    )

    # In March the old price is in force.
    march = await SqlPriceTable(factory, FixedClock(datetime(2026, 3, 1, tzinfo=UTC))).price_for(
        "openai", "gpt-4o", organization_id=org
    )
    assert march is not None
    assert march.input_price_per_1k == Decimal("1.00000000")

    # In September the new price is in force.
    september = await SqlPriceTable(
        factory, FixedClock(datetime(2026, 9, 1, tzinfo=UTC))
    ).price_for("openai", "gpt-4o", organization_id=org)
    assert september is not None
    assert september.input_price_per_1k == Decimal("3.00000000")


async def test_a_future_price_does_not_apply_before_it_is_effective(
    factory: UnitOfWorkFactory,
) -> None:
    """A price scheduled to start in December must not be charged in June - the bug that
    ``ORDER BY effective_from DESC LIMIT 1`` alone would introduce."""
    org = uuid4()
    await seed_organization(factory, org)
    model_id = await _priced_model(factory, org)
    await seed_price(
        factory, org, model_id, input_per_1k="1.00", output_per_1k="1.00", effective_from=_JAN
    )
    await seed_price(
        factory, org, model_id, input_per_1k="9.00", output_per_1k="9.00", effective_from=_DEC
    )
    price = await SqlPriceTable(factory, FixedClock(_JUN)).price_for(
        "openai", "gpt-4o", organization_id=org
    )
    assert price is not None
    assert price.input_price_per_1k == Decimal("1.00000000"), "the future price must not apply yet"


async def test_the_returned_price_carries_provider_model_and_currency(
    factory: UnitOfWorkFactory,
) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    model_id = await _priced_model(factory, org)
    await seed_price(
        factory,
        org,
        model_id,
        input_per_1k="0.50",
        output_per_1k="1.50",
        currency="EUR",
        effective_from=_JAN,
    )
    price = await SqlPriceTable(factory, FixedClock(_JUN)).price_for(
        "openai", "gpt-4o", organization_id=org
    )
    assert price is not None
    assert price.provider == "openai"
    assert price.model == "gpt-4o"
    assert price.currency == "EUR"
    assert price.input_price_per_1k == Decimal("0.50000000")
    assert price.output_price_per_1k == Decimal("1.50000000")


# ------------------------------------------------------------------ fail closed on outage


async def test_a_database_failure_raises_rather_than_looking_unpriced() -> None:
    """None becomes UnknownPriceError ("add a price") - the wrong story for an outage. Raising
    keeps the two apart so the request fails closed instead of looking misconfigured."""
    unreachable = create_database_engine(url="postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        factory = UnitOfWorkFactory(create_session_factory(unreachable), rls_enabled=True)
        with pytest.raises(PriceTableUnavailableError):
            await SqlPriceTable(factory, FixedClock(_JUN)).price_for(
                "openai", "gpt-4o", organization_id=uuid4()
            )
    finally:
        await unreachable.dispose()
