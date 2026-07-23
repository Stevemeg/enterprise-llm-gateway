"""InMemoryResponseCache tests (ADR-0016 Slice 10).

Exercises the ordinary hit/miss/TTL/fail-open contract against the fast in-memory double. Real
tenant-isolation-by-RLS and durability claims are proven separately against PostgreSQL
(tests/integration/test_response_cache_postgres.py) - this file proves the port's basic contract
and this adapter's own documented (map-keying-only) isolation, not the database guarantee.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.application.execution.cache_key import compute_cache_key
from gateway.application.ports.cache import CachedResponse, CacheKey, CacheUnavailableError

ORG = uuid4()
OTHER_ORG = uuid4()


class MovableClock:
    def __init__(self, moment: datetime | None = None) -> None:
        self._moment = moment or datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> None:
        self._moment += delta


def _key(org: UUID = ORG) -> CacheKey:
    return compute_cache_key(org, provider="openai", model="gpt-4o", payload={"prompt": "hi"})


async def test_miss_on_an_empty_cache() -> None:
    cache = InMemoryResponseCache(MovableClock())

    result = await cache.get(ORG, _key())

    assert result is None


async def test_hit_after_put() -> None:
    cache = InMemoryResponseCache(MovableClock())
    key = _key()
    entry = CachedResponse(provider="openai", model="gpt-4o", content={"text": "hello"})

    await cache.put(ORG, key, entry)
    result = await cache.get(ORG, key)

    assert result == entry


async def test_a_write_under_one_org_is_not_visible_to_another() -> None:
    cache = InMemoryResponseCache(MovableClock())
    key = _key()
    entry = CachedResponse(provider="openai", model="gpt-4o", content={"text": "hello"})

    await cache.put(ORG, key, entry)

    assert await cache.get(OTHER_ORG, key) is None


async def test_entry_expires_after_its_ttl() -> None:
    clock = MovableClock()
    cache = InMemoryResponseCache(clock, ttl=timedelta(minutes=10))
    key = _key()
    entry = CachedResponse(provider="openai", model="gpt-4o", content={"text": "hello"})
    await cache.put(ORG, key, entry)

    clock.advance(timedelta(minutes=9))
    assert await cache.get(ORG, key) == entry

    clock.advance(timedelta(minutes=2))
    assert await cache.get(ORG, key) is None


async def test_a_second_put_replaces_the_stored_entry() -> None:
    cache = InMemoryResponseCache(MovableClock())
    key = _key()
    first = CachedResponse(provider="openai", model="gpt-4o", content={"text": "first"})
    second = CachedResponse(provider="openai", model="gpt-4o", content={"text": "second"})

    await cache.put(ORG, key, first)
    await cache.put(ORG, key, second)

    assert await cache.get(ORG, key) == second


async def test_unavailable_store_raises_on_get_and_put() -> None:
    cache = InMemoryResponseCache(MovableClock(), unavailable=True)
    key = _key()

    with pytest.raises(CacheUnavailableError):
        await cache.get(ORG, key)
    with pytest.raises(CacheUnavailableError):
        await cache.put(ORG, key, CachedResponse(provider="openai", model="gpt-4o", content={}))
