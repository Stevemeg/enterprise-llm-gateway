"""Seeding helpers for the provider-catalog / pricing integration tests (Slice 19).

There is no provider-registration or price-management API in Slice 19, so tests seed the way an
operator would: direct inserts inside the tenant's own RLS context, so the ``WITH CHECK`` clause
has to accept them - a seed RLS rejected would mean the test wrote a row the application could not.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text

from gateway.adapters.persistence.uow import UnitOfWorkFactory


async def seed_provider(
    factory: UnitOfWorkFactory,
    org_id: UUID,
    *,
    name: str,
    provider_type: str = "openai_compatible",
    region: str | None = None,
    is_enabled: bool = True,
) -> UUID:
    """Insert a provider row; returns its id (the FK models hang from)."""
    provider_id = uuid4()
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO provider (id, organization_id, type, name, region, is_enabled) "
                "VALUES (:id, :org, CAST(:type AS provider_type), :name, :region, :enabled)"
            ),
            {
                "id": str(provider_id),
                "org": str(org_id),
                "type": provider_type,
                "name": name,
                "region": region,
                "enabled": is_enabled,
            },
        )
        await uow.commit()
    return provider_id


async def seed_model(
    factory: UnitOfWorkFactory,
    org_id: UUID,
    provider_id: UUID,
    *,
    name: str,
    modality: str = "chat",
    is_enabled: bool = True,
) -> UUID:
    """Insert a model row under ``provider_id``; returns its id (priced by ``seed_price``)."""
    model_id = uuid4()
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO model (id, organization_id, provider_id, name, modality, is_enabled) "
                "VALUES (:id, :org, :provider, :name, CAST(:modality AS model_modality), :enabled)"
            ),
            {
                "id": str(model_id),
                "org": str(org_id),
                "provider": str(provider_id),
                "name": name,
                "modality": modality,
                "enabled": is_enabled,
            },
        )
        await uow.commit()
    return model_id


async def seed_price(
    factory: UnitOfWorkFactory,
    org_id: UUID,
    model_id: UUID,
    *,
    input_per_1k: str,
    output_per_1k: str,
    currency: str = "USD",
    effective_from: datetime,
    effective_to: datetime | None = None,
) -> None:
    """Insert one effective-dated price row for ``model_id``."""
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO price_table (id, organization_id, model_id, currency, "
                "input_price_per_1k, output_price_per_1k, effective_from, effective_to) "
                "VALUES (:id, :org, :model, :cur, :inp, :out, :from_, :to_)"
            ),
            {
                "id": str(uuid4()),
                "org": str(org_id),
                "model": str(model_id),
                "cur": currency,
                "inp": Decimal(input_per_1k),
                "out": Decimal(output_per_1k),
                "from_": effective_from,
                "to_": effective_to,
            },
        )
        await uow.commit()
