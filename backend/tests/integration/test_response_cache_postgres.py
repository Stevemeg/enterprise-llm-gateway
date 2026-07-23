"""SqlResponseCache tests against real PostgreSQL (ADR-0016 Slice 10, ADR-0018).

Runs in Gate 2 / CI (skipped only when no Postgres URL is configured). Per ADR-0014 the connection
is the least-privilege ``app_rw`` role. These are the claims that can only be proven against a real
database, never against ``InMemoryResponseCache``: tenant isolation via RLS (including a case where
the application-level key would coincidentally collide across tenants), durable TTL expiry, a
malformed/foreign stored entry failing open rather than raising, and a genuine connection outage
failing open rather than denying the request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from gateway.adapters.cache.sql_response_cache import SqlResponseCache
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.ports.cache import CachedResponse, CacheKey, CacheUnavailableError
from tests.support.postgres import PG_URL, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


class MovableClock:
    def __init__(self) -> None:
        self._moment = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> None:
        self._moment += delta


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock()


@pytest.fixture
def cache(engine: AsyncEngine, clock: MovableClock) -> SqlResponseCache:
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    return SqlResponseCache(factory, clock)


async def _seed_org(engine: AsyncEngine, org_id: UUID) -> None:
    """Insert an organization (not RLS-scoped) - the FK parent for a cache entry."""
    slug = f"t-{org_id.hex[:16]}"
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org_id), "slug": slug, "name": f"tenant-{slug}"},
        )


@pytest.fixture
async def org(engine: AsyncEngine) -> UUID:
    org_id = uuid4()
    await _seed_org(engine, org_id)
    return org_id


def _key(org_id: UUID, prompt: str = "hi") -> CacheKey:
    return compute_cache_key(org_id, provider="openai", model="gpt-4o", payload={"prompt": prompt})


async def _raw_insert(
    engine: AsyncEngine, org_id: UUID, key: CacheKey, response_json: str, expires_at: str | None
) -> None:
    """Insert a row bypassing the adapter entirely, to plant states the adapter itself would
    never produce (malformed JSON shape, an entry belonging to a foreign key digest collision)."""
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO semantic_cache_entry "
                "(id, organization_id, request_hash, response, expires_at) "
                "VALUES (gen_random_uuid(), :org, :hash, :response, :expires_at)"
            ),
            {
                "org": str(org_id),
                "hash": key.digest,
                "response": response_json,
                "expires_at": expires_at,
            },
        )
        await uow.commit()


# ------------------------------------------------------------------ hit / miss


async def test_miss_on_an_empty_cache(cache: SqlResponseCache, org: UUID) -> None:
    result = await cache.get(org, _key(org))

    assert result is None


async def test_hit_after_put(cache: SqlResponseCache, org: UUID) -> None:
    key = _key(org)
    entry = CachedResponse(provider="openai", model="gpt-4o", content={"text": "hello"})

    await cache.put(org, key, entry)
    result = await cache.get(org, key)

    assert result == entry


async def test_a_second_put_for_the_same_key_replaces_the_entry(
    cache: SqlResponseCache, org: UUID
) -> None:
    key = _key(org)
    await cache.put(org, key, CachedResponse(provider="openai", model="gpt-4o", content={"v": 1}))
    await cache.put(org, key, CachedResponse(provider="openai", model="gpt-4o", content={"v": 2}))

    result = await cache.get(org, key)

    assert result is not None
    assert result.content == {"v": 2}


# ------------------------------------------------------------------ TTL expiry


async def test_entry_expires_after_its_ttl(
    engine: AsyncEngine, clock: MovableClock, org: UUID
) -> None:
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    cache = SqlResponseCache(factory, clock, ttl=timedelta(minutes=10))
    key = _key(org)
    await cache.put(org, key, CachedResponse(provider="openai", model="gpt-4o", content={}))

    clock.advance(timedelta(minutes=9))
    assert await cache.get(org, key) is not None

    clock.advance(timedelta(minutes=2))
    assert await cache.get(org, key) is None


# ------------------------------------------------------------------ malformed / foreign entries


async def test_a_malformed_stored_entry_is_treated_as_a_miss_not_an_error(
    engine: AsyncEngine, cache: SqlResponseCache, org: UUID
) -> None:
    """A row this adapter did not write itself (or wrote under a different, older version)
    must fail open to a miss - never raise, never be served."""
    key = _key(org)
    await _raw_insert(engine, org, key, response_json='{"unexpected": "shape"}', expires_at=None)

    result = await cache.get(org, key)

    assert result is None


# ------------------------------------------------------------------ tenant isolation (RLS)


async def test_cross_tenant_lookup_is_isolated_by_rls_even_for_a_colliding_key(
    engine: AsyncEngine, clock: MovableClock
) -> None:
    """Defence in depth: even if two tenants' application-level keys ever collided (they cannot,
    by construction - see cache_key.py - but this adapter must not rely on that alone), RLS must
    still prevent one tenant's cache adapter call from ever returning another tenant's entry."""
    org_a, org_b = uuid4(), uuid4()
    await _seed_org(engine, org_a)
    await _seed_org(engine, org_b)
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    cache = SqlResponseCache(factory, clock)
    colliding_key = CacheKey(b"\x11" * 32)

    await cache.put(
        org_a, colliding_key, CachedResponse(provider="openai", model="m", content={"owner": "a"})
    )

    assert await cache.get(org_b, colliding_key) is None


async def test_writes_under_two_tenants_with_the_same_key_do_not_interfere(
    engine: AsyncEngine, clock: MovableClock
) -> None:
    org_a, org_b = uuid4(), uuid4()
    await _seed_org(engine, org_a)
    await _seed_org(engine, org_b)
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    cache = SqlResponseCache(factory, clock)
    colliding_key = CacheKey(b"\x22" * 32)

    await cache.put(
        org_a, colliding_key, CachedResponse(provider="openai", model="m", content={"owner": "a"})
    )
    await cache.put(
        org_b, colliding_key, CachedResponse(provider="openai", model="m", content={"owner": "b"})
    )

    result_a = await cache.get(org_a, colliding_key)
    result_b = await cache.get(org_b, colliding_key)

    assert result_a is not None
    assert result_a.content == {"owner": "a"}
    assert result_b is not None
    assert result_b.content == {"owner": "b"}


# ------------------------------------------------------------------ fail-open on outage


async def test_unreachable_store_fails_open_with_cache_unavailable_error() -> None:
    bad_engine = create_async_engine("postgresql+asyncpg://nouser:nopass@localhost:1/nodb")
    factory = UnitOfWorkFactory(create_session_factory(bad_engine), rls_enabled=True)
    cache = SqlResponseCache(factory, MovableClock())

    with pytest.raises(CacheUnavailableError):
        await cache.get(uuid4(), CacheKey(b"\x33" * 32))
    with pytest.raises(CacheUnavailableError):
        await cache.put(
            uuid4(), CacheKey(b"\x33" * 32), CachedResponse(provider="p", model="m", content={})
        )

    await bad_engine.dispose()
