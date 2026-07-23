"""Response cache seam (ADR-0016 Slice 10) - a **capability-owned** port, not a Tier-1 protocol.

Tier 1 is untouched: this port models nothing ``RoutingDecision``, ``RoutingExecution``,
``PipelineStage`` or ``BaseAgent`` already own. It exists so a caching layer can sit around
``ProviderExecutor`` without either side depending on a storage technology.

## Cache identity vs. execution identity (Rule 3)

A cache entry's identity is *content*-based: ``(organization_id, provider, model, canonical
payload)``. It is deliberately independent of ``InferenceRequest.correlation_id`` - two different
requests (different correlation ids) that ask for the same thing from the same provider/model are
the same cache entry by design; that is the entire value of caching. Conflating the two identities
would either (a) make every request a permanent cache miss (if ``correlation_id`` leaked into the
key) or (b) treat two genuinely different logical requests as one (if the key were ever built from
``correlation_id`` alone). See ``application/execution/cache_key.py`` for the canonicalization, and
``application/execution/deduplicator.py`` for why deduplication is deliberately a different concept
keyed a different way.

## Fail-open, not fail-closed

Unlike ``BudgetLedgerPort`` (ADR-0009 row 1: an unavailable budget store fails closed, denying the
request), an unavailable cache fails *open* to a miss. A cache is an optimization: the correct
answer without it is simply "call the provider," which is exactly what a miss already does.
Treating an outage as a miss is not a security relaxation - nothing the cache could have skipped
(a budget check, an authorization check) is ever bypassed differently on a miss than it would be
with an empty cache. ``CacheUnavailableError`` exists so the adapter can say "I could not answer"
honestly; ``InferenceCoordinator`` - not this port, and not any adapter - is the one that decides
to treat that as an ordinary miss / a dropped write (mirrors how ``ReservationService`` catches
``LedgerUnavailableError``, just fail-open here instead of fail-closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

_SHA256_DIGEST_SIZE = 32


@dataclass(frozen=True, slots=True)
class CacheKey:
    """A deterministic, cryptographic identity for one cacheable request.

    Wraps a raw digest rather than passing ``bytes`` around bare (Rule 3): a cache key and an
    arbitrary byte blob are different concepts, and a bare ``bytes`` parameter would let a caller
    pass the wrong one with no type error to catch it. See ``cache_key.py`` for construction -
    this type does not compute a digest itself, only carries and validates one.
    """

    digest: bytes

    def __post_init__(self) -> None:
        if len(self.digest) != _SHA256_DIGEST_SIZE:
            raise ValueError(
                f"CacheKey digest must be {_SHA256_DIGEST_SIZE} bytes (SHA-256), "
                f"got {len(self.digest)}"
            )

    @property
    def hex(self) -> str:
        return self.digest.hex()


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """What a cache entry stores: enough to answer a repeat request, and nothing else.

    Deliberately carries no ``ProviderUsage`` and no cost: a cache hit never incurred either (see
    ``application/execution/inference_coordinator.py``), and storing a number that would be
    misread as "this call's usage" would misrepresent an observation that never happened - the
    same discipline ``ProviderResponse.usage`` and ``CostAccountant.MissingUsageError`` already
    apply to a different case.
    """

    provider: str
    model: str
    content: Any


class CacheUnavailableError(RuntimeError):
    """The cache store could not be reached, or a write could not be completed.

    Never a business outcome. Contrast ``LedgerUnavailableError``: that one is caught and turned
    into a fail-**closed** decision (deny the request). This one is caught and turned into a
    fail-**open** decision (treat as a miss on read, drop the write on write) - a cache exists to
    make an already-correct path faster, and losing that speed-up is never a reason to fail a
    request that would otherwise have succeeded.
    """


@runtime_checkable
class ResponseCachePort(Protocol):
    """Tenant-scoped storage for exact-match cacheable responses."""

    async def get(self, organization_id: UUID, key: CacheKey) -> CachedResponse | None:
        """Look up a cache entry. ``None`` for an ordinary miss, an expired entry, or a stored
        entry this process cannot parse back into a ``CachedResponse`` - all three are "nothing
        usable here", and the caller must not need to (and cannot) tell them apart.

        Raises ``CacheUnavailableError`` if the store itself cannot be reached - never returns a
        fabricated value to paper over an outage; never raises for an ordinary miss.
        """
        ...

    async def put(self, organization_id: UUID, key: CacheKey, response: CachedResponse) -> None:
        """Store a cache entry, replacing any existing entry under the same key.

        Raises ``CacheUnavailableError`` if the write could not be completed. The response being
        cached has already been returned to its own caller by the time this runs (see
        ``InferenceCoordinator``), so a failure here must never be allowed to fail that request.
        """
        ...
