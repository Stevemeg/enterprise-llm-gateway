"""In-process token-bucket rate limiter (Phase 5 M3) - the Rule-4 first implementation of
``RateLimiterPort``.

One bucket per ``organization_id``, refilled continuously at ``requests_per_second`` up to a
capacity of ``burst``. Taking a token allows a request; an empty bucket denies it and reports how
long until the next token exists.

Token bucket rather than a fixed window because ``docs/API_Rate_Limiting.md`` §4 decides it
("RPS smoothing via bucket refill"), and because a fixed window has a failure mode that matters
here: a tenant can send a full window's allowance in the last instant of one window and again in
the first instant of the next, delivering twice the intended burst against the provider pool at the
exact moment the counter looks compliant.

## Tenant isolation is the key, and the key is not attacker-supplied

State is keyed by ``organization_id`` alone - the same "isolation by key rather than by RLS"
posture ``InMemoryCircuitBreaker`` documents for state that never reaches the database. One
tenant's exhaustion can never deny another's request, because their buckets are different dict
entries and nothing merges them.

The key arrives from ``AuthenticationContext.organization_id``, which the authentication middleware
derived from a verified credential. No header, query parameter or body field reaches this class, so
a caller cannot spend another tenant's allowance or mint buckets to exhaust memory: the key space is
bounded by the number of organizations that actually hold credentials, not by request volume. That
is also why no eviction policy is built - there is no unbounded growth to evict, and a sweeper
nothing needs would be speculative machinery (Rule 5).

## Time, determinism and monotonicity

Refill is driven by an injected ``Clock``, never ``time.time()``, so tests advance time
deterministically rather than sleeping. The clock is wall-clock UTC, which can in principle step
backwards (NTP correction); ``_refill`` therefore floors the elapsed interval at zero. A backwards
step then costs a tenant a little refill rather than granting an unbounded one, which is the safe
direction for a protective control.

Not thread-safe, and deliberately not locked: the gateway serves each request on one asyncio task
in one event loop, and ``acquire`` contains no ``await`` between reading and writing a bucket, so
it is atomic with respect to other tasks by construction. A multi-process deployment does not share
these buckets at all - each replica enforces the limit independently, an honest limitation recorded
in the evidence log rather than a distributed guarantee this class cannot make.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from gateway.application.ports.rate_limit import RateLimitDecision, RateLimitPolicy
from gateway.shared.clock import Clock


@dataclass
class _Bucket:
    """Mutable per-tenant state: how many tokens remain, and when that was last true."""

    tokens: float
    updated_at: datetime


class InMemoryTokenBucketRateLimiter:
    """Per-organization token bucket held in process memory."""

    def __init__(self, clock: Clock, policy: RateLimitPolicy) -> None:
        self._clock = clock
        self._policy = policy
        self._buckets: dict[UUID, _Bucket] = {}

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        now = self._clock.now()
        bucket = self._buckets.get(organization_id)
        if bucket is None:
            # A tenant seen for the first time starts full: absence of history is not evidence of
            # abuse, the same posture the circuit breaker takes for an unseen provider.
            bucket = _Bucket(tokens=float(self._policy.burst), updated_at=now)
            self._buckets[organization_id] = bucket
        else:
            self._refill(bucket, now)

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return RateLimitDecision(
                allowed=True,
                limit=self._policy.burst,
                remaining=int(bucket.tokens),
                reset_seconds=self._seconds_to_full(bucket),
            )

        # Denied. Nothing is consumed, so hammering cannot push recovery further away.
        return RateLimitDecision(
            allowed=False,
            limit=self._policy.burst,
            remaining=0,
            reset_seconds=self._seconds_to_full(bucket),
            retry_after_seconds=self._seconds_to_next_token(bucket),
        )

    def _refill(self, bucket: _Bucket, now: datetime) -> None:
        """Add the tokens that accrued since the last look, capped at the bucket's capacity."""
        elapsed = max(0.0, (now - bucket.updated_at).total_seconds())
        bucket.tokens = min(
            float(self._policy.burst),
            bucket.tokens + elapsed * self._policy.requests_per_second,
        )
        bucket.updated_at = now

    def _seconds_to_next_token(self, bucket: _Bucket) -> int:
        """Whole seconds until one token exists, floored at 1.

        Never 0: ``Retry-After: 0`` invites an immediate retry that this bucket would deny again,
        turning the header into an instruction to hammer. Rounded **up**, so a client that obeys it
        succeeds rather than arriving fractionally early and being denied a second time.
        """
        deficit = 1.0 - bucket.tokens
        return max(1, math.ceil(deficit / self._policy.requests_per_second))

    def _seconds_to_full(self, bucket: _Bucket) -> int:
        """Whole seconds until the allowance is fully restored, for the ``RateLimit`` header."""
        deficit = self._policy.burst - bucket.tokens
        if deficit <= 0:
            return 0
        return max(1, math.ceil(deficit / self._policy.requests_per_second))
