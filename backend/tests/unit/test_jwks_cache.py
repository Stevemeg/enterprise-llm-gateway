"""IdP JWKS cache: TTL, rotation-aware refresh, and fail-closed behaviour (ADR-0015)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from gateway.adapters.security.jwks_cache import DEFAULT_JWKS_TTL, JwksCache, JwksFetchError


class MovableClock:
    def __init__(self, moment: datetime | None = None) -> None:
        self._moment = moment or datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> None:
        self._moment += delta


class FakeTransport:
    """Serves a scripted JWKS document and counts fetches."""

    def __init__(self, *documents: Any) -> None:
        self._documents = list(documents)
        self.calls = 0

    async def fetch(self) -> dict[str, Any]:
        self.calls += 1
        document = self._documents[min(self.calls - 1, len(self._documents) - 1)]
        if isinstance(document, Exception):
            raise document
        result: dict[str, Any] = document
        return result


def _jwks(*kids: str) -> dict[str, Any]:
    return {"keys": [{"kid": k, "kty": "RSA", "n": "x", "e": "AQAB"} for k in kids]}


async def test_first_lookup_fetches_then_cache_hit_avoids_network() -> None:
    transport = FakeTransport(_jwks("k1"))
    cache = JwksCache(transport, MovableClock())

    assert (await cache.get_key("k1"))["kid"] == "k1"
    assert (await cache.get_key("k1"))["kid"] == "k1"
    assert transport.calls == 1, "a cache hit must not re-fetch"


async def test_unknown_kid_triggers_refresh_and_resolves_rotation() -> None:
    """IdP rotated to k2: the unknown kid forces a refresh that picks it up."""
    transport = FakeTransport(_jwks("k1"), _jwks("k1", "k2"))
    clock = MovableClock()
    cache = JwksCache(transport, clock)

    await cache.get_key("k1")
    clock.advance(timedelta(minutes=1))  # past the min refresh interval, within TTL

    assert (await cache.get_key("k2"))["kid"] == "k2"
    assert transport.calls == 2


async def test_retired_key_disappears_after_rotation() -> None:
    transport = FakeTransport(_jwks("old"), _jwks("new"))
    clock = MovableClock()
    cache = JwksCache(transport, clock)

    await cache.get_key("old")
    clock.advance(timedelta(minutes=1))
    await cache.get_key("new")
    clock.advance(timedelta(minutes=1))

    with pytest.raises(JwksFetchError):
        await cache.get_key("old")


async def test_unknown_kid_after_refresh_fails_closed() -> None:
    transport = FakeTransport(_jwks("k1"))
    cache = JwksCache(transport, MovableClock())

    with pytest.raises(JwksFetchError, match="unknown signing key"):
        await cache.get_key("forged-kid")


async def test_unreachable_jwks_fails_closed() -> None:
    transport = FakeTransport(RuntimeError("connection refused"))
    cache = JwksCache(transport, MovableClock())

    with pytest.raises(JwksFetchError):
        await cache.get_key("k1")


@pytest.mark.parametrize(
    "document", [{}, {"keys": []}, {"keys": "nope"}, {"keys": [{"kty": "RSA"}]}]
)
async def test_malformed_jwks_fails_closed(document: Any) -> None:
    cache = JwksCache(FakeTransport(document), MovableClock())

    with pytest.raises(JwksFetchError):
        await cache.get_key("k1")


async def test_expired_cache_refetches_rather_than_serving_stale_keys() -> None:
    transport = FakeTransport(_jwks("k1"))
    clock = MovableClock()
    cache = JwksCache(transport, clock)

    await cache.get_key("k1")
    clock.advance(timedelta(minutes=11))  # past the 10-minute TTL
    await cache.get_key("k1")

    assert transport.calls == 2


async def test_forged_kid_flood_is_rate_limited() -> None:
    """Unknown kids must not let an attacker amplify traffic at the IdP."""
    transport = FakeTransport(_jwks("k1"))
    clock = MovableClock()
    cache = JwksCache(transport, clock)

    await cache.get_key("k1")  # 1 fetch, cache now populated
    for _ in range(5):
        with pytest.raises(JwksFetchError):
            await cache.get_key("forged")  # within min refresh interval

    assert transport.calls == 1, "throttle must suppress refresh storms"


async def test_jwks_cache_does_not_refresh_before_ttl() -> None:
    """Under normal conditions the cache must make no unnecessary network calls.

    Complements the unknown-kid refresh test: repeated verifications of a *known* kid across
    the whole TTL window must be served entirely from cache (exactly one fetch).
    """
    transport = FakeTransport(_jwks("k1"))
    clock = MovableClock()
    cache = JwksCache(transport, clock)

    await cache.get_key("k1")
    assert transport.calls == 1

    # Walk right up to (but not past) the TTL boundary, verifying repeatedly.
    for _ in range(9):
        clock.advance(DEFAULT_JWKS_TTL / 10)
        assert (await cache.get_key("k1"))["kid"] == "k1"

    assert transport.calls == 1, "known kid within TTL must never trigger a refresh"


async def test_jwks_timeout_is_reported_as_a_fetch_failure() -> None:
    """A timed-out JWKS fetch must fail closed (and is labelled as a timeout for metrics)."""
    cache = JwksCache(FakeTransport(TimeoutError("read timed out")), MovableClock())

    with pytest.raises(JwksFetchError, match="timed out"):
        await cache.get_key("k1")
