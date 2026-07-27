"""Shared token-bucket rate limiter on Redis (Phase 5 M4, ADR-0021) - the Rule-4 **second**
implementation of ``RateLimiterPort``.

This class is the evidence for M4's central claim. The port, ``RateLimitDecision``,
``RateLimitMiddleware`` and the whole delivery layer are **byte-unchanged** from M3; swapping a
process-local bucket for one shared by every replica is a choice the composition root makes and
nothing else in the system observes. Where that claim turned out to be false - the circuit breaker
and the deduplicator, whose seams cannot express distributed semantics - ADR-0021 records why, and
this milestone stopped instead of bending them.

## The whole decision is one atomic script, and that is not an optimisation

A token bucket is read-modify-write: read the level, add the accrual, subtract one, write it back.
Split across a ``GET`` and a ``SET`` it is a lost-update race, and the update that gets lost is a
token *someone already spent* - so under concurrency the limiter admits more than its limit,
silently, exactly when load is high enough for the limit to matter. Redis runs ``EVAL`` scripts
atomically against a single-threaded core, so the whole read-modify-write is one indivisible step
against one key. ``WATCH``/``MULTI`` with a retry loop would also be correct, but it converts
contention into retries at precisely the moment a tenant is being throttled.

Rejected alternative: ``INCR`` with ``EXPIRE`` (a fixed window). It is simpler and needs no script,
but it lets a tenant spend a full window's allowance at the end of one window and again at the start
of the next - twice the intended burst arriving at the provider pool while the counter still looks
compliant. ``docs/API_Rate_Limiting.md`` §4 specifies bucket refill for this reason.

## Time comes from Redis, not from this process

``TIME`` is read **inside** the script, so every replica's arithmetic uses one clock. Passing a
client-side timestamp in would make refill a function of whichever replica happened to serve the
request, and a single node with a skewed clock could mint tokens for a tenant across the whole
deployment. This is the one place the injected ``Clock`` is deliberately *not* used: the port needs
a shared clock, and the shared store is the only thing that has one.

## Keys carry tenant identity and nothing else

``{prefix}:rl:{organization_id}`` - a version-free, payload-free key. No prompt, no credential, no
correlation id, no principal: Redis is not covered by RLS, so nothing may be stored there that would
matter if it leaked, and the value is two floats. Tenant isolation is by key, the same posture
``InMemoryCircuitBreaker`` documents for state that never reaches the database, and it is proven
against real Redis rather than asserted.

The ``prefix`` is configurable so two deployments sharing one Redis (a dev box, a staging cluster)
cannot silently share buckets. Every key carries a TTL of the bucket's full refill time, so an idle
tenant's key expires on its own: no sweeper, no unbounded keyspace growth, and a tenant that returns
after the TTL starts full - which is exactly what it would have refilled to anyway, so expiry
changes no answer.

## Outage behaviour is degraded-closed, and it is the caller's, not this class's

Any Redis failure is re-raised as ``RateLimiterUnavailableError``. This class does **not** decide
what that means - it reports that it could not answer, and ``DegradedRateLimiter`` (composed in the
composition root) owns the fallback ADR-0021 chose. Keeping the two apart is what lets the fail mode
be re-decided later without touching the Redis integration, and what keeps this class honest: it
never fabricates an answer it did not get.
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from gateway.application.ports.rate_limit import (
    RateLimitDecision,
    RateLimiterUnavailableError,
    RateLimitPolicy,
)

#: Atomic refill-and-take, evaluated inside Redis against one key.
#:
#: KEYS[1]  bucket key
#: ARGV[1]  burst (bucket capacity, tokens)
#: ARGV[2]  refill rate (tokens per second)
#: returns  {allowed, remaining, reset_seconds, retry_after_seconds}
#:
#: ``TIME`` returns {seconds, microseconds} from the Redis server, so all replicas share one clock.
#: A first-seen tenant starts full - absence of history is not evidence of abuse, the same posture
#: the in-process bucket and the circuit breaker both take.
_ACQUIRE_SCRIPT = """
local burst = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])

local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) + (tonumber(now_parts[2]) / 1000000)

local stored = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(stored[1])
local updated_at = tonumber(stored[2])

if tokens == nil or updated_at == nil then
  tokens = burst
  updated_at = now
end

-- max(0, ...) so a backwards server-clock step costs a little refill rather than minting tokens.
local elapsed = now - updated_at
if elapsed < 0 then elapsed = 0 end
tokens = math.min(burst, tokens + (elapsed * rate))

local allowed = 0
if tokens >= 1 then
  allowed = 1
  tokens = tokens - 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_at', now)

-- Expire when the bucket would be full again: an idle tenant's key removes itself, and a tenant
-- returning after that starts full, which is what a full refill would have given it anyway.
local ttl = math.ceil((burst - tokens) / rate)
if ttl < 1 then ttl = 1 end
redis.call('EXPIRE', KEYS[1], ttl)

local retry_after = 0
if allowed == 0 then
  retry_after = math.ceil((1 - tokens) / rate)
  if retry_after < 1 then retry_after = 1 end
end

return {allowed, math.floor(tokens), ttl, retry_after}
"""


class RedisTokenBucketRateLimiter:
    """Per-organization token bucket shared by every replica through Redis."""

    def __init__(
        self,
        client: Redis,
        policy: RateLimitPolicy,
        *,
        key_prefix: str = "gateway",
    ) -> None:
        self._client = client
        self._policy = policy
        self._key_prefix = key_prefix
        # register_script uses EVALSHA with an automatic EVAL fallback, so a restarted or
        # script-flushed Redis recovers by itself rather than erroring once per replica.
        self._acquire = client.register_script(_ACQUIRE_SCRIPT)

    def _key(self, organization_id: UUID) -> str:
        return f"{self._key_prefix}:rl:{organization_id}"

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        try:
            raw = await self._acquire(
                keys=[self._key(organization_id)],
                args=[self._policy.burst, self._policy.requests_per_second],
            )
        except (RedisError, OSError) as exc:
            # Includes connection refused, timeouts and a script error. Never converted into a
            # denial: "could not answer" and "no" demand different responses, and collapsing them
            # would make an outage indistinguishable from a tenant genuinely over its allowance.
            raise RateLimiterUnavailableError(
                f"rate-limit store unavailable ({type(exc).__name__})"
            ) from exc

        allowed, remaining, reset_seconds, retry_after = (int(value) for value in raw)
        return RateLimitDecision(
            allowed=bool(allowed),
            limit=self._policy.burst,
            remaining=remaining,
            reset_seconds=reset_seconds,
            retry_after_seconds=None if allowed else max(1, retry_after),
        )
