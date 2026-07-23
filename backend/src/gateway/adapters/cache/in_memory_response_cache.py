"""Single-process, in-memory ResponseCachePort (ADR-0016 Slice 10, Rule 4).

## Documented limitations (not omissions) - mirrors ``InMemoryBudgetLedger``'s own disclosure

- **Not durable.** A process restart forgets every cached entry - correct for tests and any
  Postgres-less profile, never advertised as more.
- **Not distributed.** Two gateway replicas each keep an independent cache; a hit on one is a miss
  on the other. Acceptable for a cache (unlike a budget ledger): a miss just means "call the
  provider," never an incorrect answer.
- **Tenant isolation here is explicit map-keying, not RLS.** Correct in effect (this adapter never
  returns a value stored under a different key), but it does not exercise the same defence-in-depth
  property ``SqlResponseCache`` proves against real PostgreSQL (Postgres would deny a cross-tenant
  row even if the application query forgot to filter by ``organization_id`` - this class has no
  second layer to fall back on if its own key construction were ever wrong).

Never raises ``CacheUnavailableError`` except via the construction-time ``unavailable`` toggle,
which exists purely so ``InferenceCoordinator``/container tests can exercise the fail-open path
without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from gateway.application.ports.cache import CachedResponse, CacheKey, CacheUnavailableError
from gateway.shared.clock import Clock

_DEFAULT_TTL = timedelta(hours=1)


@dataclass
class _Entry:
    response: CachedResponse
    expires_at: datetime


class InMemoryResponseCache:
    """Org-scoped exact-match cache, held entirely in process memory."""

    def __init__(
        self, clock: Clock, *, ttl: timedelta = _DEFAULT_TTL, unavailable: bool = False
    ) -> None:
        self._clock = clock
        self._ttl = ttl
        self._unavailable = unavailable
        self._store: dict[tuple[UUID, bytes], _Entry] = {}

    async def get(self, organization_id: UUID, key: CacheKey) -> CachedResponse | None:
        if self._unavailable:
            raise CacheUnavailableError("simulated cache store outage")
        entry = self._store.get((organization_id, key.digest))
        if entry is None:
            return None
        if entry.expires_at <= self._clock.now():
            return None
        return entry.response

    async def put(self, organization_id: UUID, key: CacheKey, response: CachedResponse) -> None:
        if self._unavailable:
            raise CacheUnavailableError("simulated cache store outage")
        self._store[(organization_id, key.digest)] = _Entry(
            response=response, expires_at=self._clock.now() + self._ttl
        )
