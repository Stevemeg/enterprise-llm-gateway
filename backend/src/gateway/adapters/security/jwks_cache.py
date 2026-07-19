"""Cached IdP JWKS with rotation-aware refresh and fail-closed behaviour (ADR-0015).

Policy (documented in ADR-0015):
  1. **Cache hit** — ``kid`` known and within TTL (10 min) ⇒ verify locally, no network call.
  2. **Unknown kid** ⇒ refresh immediately (the IdP rotated keys), subject to a minimum refresh
     interval so forged ``kid``s cannot be used to hammer the IdP (a cheap DoS amplifier).
  3. **Still unknown, or JWKS unreachable/malformed** ⇒ **fail closed** — reject the login. We
     never accept an unverified token and never fall back to expired cache entries on error.

Only this adapter layer touches the JWKS wire format; the application layer sees verified claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from gateway.observability.metrics import (
    REASON_MALFORMED,
    REASON_RATE_LIMITED,
    REASON_TIMEOUT,
    REASON_TRANSPORT,
    REASON_UNKNOWN_KID,
    oidc_jwks_fetch_failures,
)
from gateway.shared.clock import Clock

DEFAULT_JWKS_TTL = timedelta(minutes=10)
DEFAULT_MIN_REFRESH_INTERVAL = timedelta(seconds=30)


class JwksFetchError(Exception):
    """JWKS could not be retrieved or parsed — callers must fail closed."""


class JwksTransport(Protocol):
    """Fetches the raw JWKS document. Implemented by the HTTP adapter; faked in tests."""

    async def fetch(self) -> dict[str, Any]: ...


@dataclass
class _CacheState:
    keys: dict[str, dict[str, Any]] = field(default_factory=dict)
    fetched_at: datetime | None = None
    last_attempt_at: datetime | None = None


class JwksCache:
    """TTL cache of IdP signing keys, keyed by ``kid``."""

    def __init__(
        self,
        transport: JwksTransport,
        clock: Clock,
        *,
        ttl: timedelta = DEFAULT_JWKS_TTL,
        min_refresh_interval: timedelta = DEFAULT_MIN_REFRESH_INTERVAL,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._ttl = ttl
        self._min_refresh_interval = min_refresh_interval
        self._state = _CacheState()

    @property
    def _is_fresh(self) -> bool:
        fetched_at = self._state.fetched_at
        return fetched_at is not None and (self._clock.now() - fetched_at) < self._ttl

    async def refresh(self) -> None:
        """Fetch and replace the cached key set. Raises ``JwksFetchError`` on any failure."""
        now = self._clock.now()
        self._state.last_attempt_at = now
        try:
            document = await self._transport.fetch()
        except TimeoutError as exc:
            oidc_jwks_fetch_failures.labels(reason=REASON_TIMEOUT).inc()
            raise JwksFetchError("JWKS fetch timed out") from exc
        except Exception as exc:
            oidc_jwks_fetch_failures.labels(reason=REASON_TRANSPORT).inc()
            raise JwksFetchError("JWKS could not be fetched") from exc
        keys = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(keys, list) or not keys:
            oidc_jwks_fetch_failures.labels(reason=REASON_MALFORMED).inc()
            raise JwksFetchError("JWKS document is malformed or empty")
        parsed: dict[str, dict[str, Any]] = {}
        for key in keys:
            if isinstance(key, dict) and isinstance(key.get("kid"), str):
                parsed[key["kid"]] = key
        if not parsed:
            oidc_jwks_fetch_failures.labels(reason=REASON_MALFORMED).inc()
            raise JwksFetchError("JWKS contained no usable keys (missing 'kid')")
        # Replace wholesale so retired keys disappear on rotation.
        self._state.keys = parsed
        self._state.fetched_at = now

    async def get_key(self, kid: str) -> dict[str, Any]:
        """Return the JWK for ``kid``, refreshing on miss. Fails closed if unresolvable."""
        if self._is_fresh and kid in self._state.keys:
            return self._state.keys[kid]

        if not self._may_attempt_refresh():
            oidc_jwks_fetch_failures.labels(reason=REASON_RATE_LIMITED).inc()
            raise JwksFetchError(f"unknown signing key '{kid}' (refresh rate-limited)")

        await self.refresh()
        key = self._state.keys.get(kid)
        if key is None:
            oidc_jwks_fetch_failures.labels(reason=REASON_UNKNOWN_KID).inc()
            raise JwksFetchError(f"unknown signing key '{kid}' after JWKS refresh")
        return key

    def _may_attempt_refresh(self) -> bool:
        """Throttle refreshes so forged ``kid``s cannot amplify traffic at the IdP."""
        last = self._state.last_attempt_at
        if last is None or self._state.fetched_at is None:
            return True  # never fetched successfully — always allow the first attempt
        return (self._clock.now() - last) >= self._min_refresh_interval
