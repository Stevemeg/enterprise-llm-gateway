"""Durable provider catalog against real PostgreSQL (ADR-0003, Slice 19).

Runs as ``app_rw`` (ADR-0014), so tenant isolation is RLS's doing, not a WHERE clause's.
Failure-first: everything that must NOT appear as a candidate (another tenant's provider, a
disabled provider, a provider whose only model is disabled) is asserted before the happy path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.catalog.sql_provider_catalog import (
    ProviderCatalogUnavailableError,
    SqlProviderCatalog,
)
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from tests.support.catalog import seed_model, seed_provider
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]


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


# ------------------------------------------------------------------ fail closed / exclusions


async def test_an_empty_catalog_is_an_empty_tuple_not_an_error(factory: UnitOfWorkFactory) -> None:
    """An org with no providers is a valid state that flows into the runtime as NO_CANDIDATE - an
    explained refusal, not an exception."""
    org = uuid4()
    await seed_organization(factory, org)
    assert await SqlProviderCatalog(factory).candidates(org) == ()


async def test_one_tenants_providers_are_invisible_to_another(factory: UnitOfWorkFactory) -> None:
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        await seed_organization(factory, org)
    provider_id = await seed_provider(factory, org_a, name="openai")
    await seed_model(factory, org_a, provider_id, name="gpt-4o")

    catalog = SqlProviderCatalog(factory)
    assert [d.name for d in await catalog.candidates(org_a)] == ["openai"]
    assert await catalog.candidates(org_b) == ()
    assert await catalog.get(org_b, "openai") is None


async def test_a_disabled_provider_is_not_a_candidate(factory: UnitOfWorkFactory) -> None:
    """FR-028: runtime disable must take effect immediately. A startup snapshot would keep routing
    to it - this is why the catalog reads through to the database on every call."""
    org = uuid4()
    await seed_organization(factory, org)
    provider_id = await seed_provider(factory, org, name="openai", is_enabled=False)
    await seed_model(factory, org, provider_id, name="gpt-4o")
    assert await SqlProviderCatalog(factory).candidates(org) == ()


async def test_a_provider_whose_only_model_is_disabled_is_not_a_candidate(
    factory: UnitOfWorkFactory,
) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    provider_id = await seed_provider(factory, org, name="openai")
    await seed_model(factory, org, provider_id, name="gpt-4o", is_enabled=False)
    assert await SqlProviderCatalog(factory).candidates(org) == ()


# ------------------------------------------------------------------ the answer it gives


async def test_a_provider_with_several_models_appears_once_deterministically(
    factory: UnitOfWorkFactory,
) -> None:
    """The runtime's candidate vocabulary is provider NAMES, so a provider must resolve to one
    descriptor or ``get`` becomes ambiguous. The pick is the first model by name, stably."""
    org = uuid4()
    await seed_organization(factory, org)
    provider_id = await seed_provider(factory, org, name="openai", region="us-east")
    for model_name in ("gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"):
        await seed_model(factory, org, provider_id, name=model_name)

    catalog = SqlProviderCatalog(factory)
    candidates = await catalog.candidates(org)
    assert [d.name for d in candidates] == ["openai"]
    assert candidates[0].model == "gpt-3.5-turbo"  # first by name
    assert candidates[0].region == "us-east"
    # Stable across calls (re-read, not a cached snapshot).
    assert (await catalog.candidates(org))[0].model == "gpt-3.5-turbo"


async def test_get_resolves_only_an_enabled_offered_provider(factory: UnitOfWorkFactory) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    enabled = await seed_provider(factory, org, name="openai")
    await seed_model(factory, org, enabled, name="gpt-4o")
    disabled = await seed_provider(factory, org, name="anthropic", is_enabled=False)
    await seed_model(factory, org, disabled, name="claude")

    catalog = SqlProviderCatalog(factory)
    assert (await catalog.get(org, "openai")) is not None
    assert (await catalog.get(org, "anthropic")) is None
    assert (await catalog.get(org, "nonexistent")) is None


async def test_a_provider_with_no_region_defaults_to_global(factory: UnitOfWorkFactory) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    provider_id = await seed_provider(factory, org, name="local", region=None)
    await seed_model(factory, org, provider_id, name="llama")
    descriptor = await SqlProviderCatalog(factory).get(org, "local")
    assert descriptor is not None
    assert descriptor.region == "global"


# ------------------------------------------------------------------ fail closed on outage


async def test_a_database_failure_raises_rather_than_reporting_no_providers() -> None:
    """An outage reported as an empty catalog would say "you have no providers configured" for
    what is actually "we cannot tell" - so it is raised, and the routing stage fails closed."""
    unreachable = create_database_engine(url="postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        factory = UnitOfWorkFactory(create_session_factory(unreachable), rls_enabled=True)
        with pytest.raises(ProviderCatalogUnavailableError):
            await SqlProviderCatalog(factory).candidates(uuid4())
    finally:
        await unreachable.dispose()
