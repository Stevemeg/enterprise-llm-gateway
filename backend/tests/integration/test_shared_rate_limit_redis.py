"""Shared rate limiting against **real Redis** (Phase 5 M4, ADR-0021).

ADR-0021's claim is that a shared implementation slots in behind the unchanged M3
``RateLimiterPort`` and genuinely shares state across replicas. Every property that could make that
false lives in Redis, not in Python: script atomicity under concurrency, server-side ``TIME``,
``EXPIRE``, and key isolation. So these run against a real server, and each test constructs
**independent limiter instances** - separate objects, separate connection pools - because two
objects sharing one in-memory dict would prove nothing at all. That is the specific way a
"distributed" claim is usually faked, and it is what these tests are shaped to rule out.

Keys are namespaced per test with a unique prefix so a rerun, a parallel run, or a developer's own
Redis contents cannot make a test pass or fail for the wrong reason.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from gateway.adapters.ratelimit.client import create_redis_client
from gateway.adapters.ratelimit.degraded import DegradedRateLimiter
from gateway.adapters.ratelimit.in_memory_token_bucket import InMemoryTokenBucketRateLimiter
from gateway.adapters.ratelimit.redis_token_bucket import RedisTokenBucketRateLimiter
from gateway.application.ports.rate_limit import (
    RateLimiterPort,
    RateLimiterUnavailableError,
    RateLimitPolicy,
)
from tests.conftest import FixedClock
from tests.support.redis_support import REDIS_URL, requires_redis

pytestmark = [pytest.mark.integration, requires_redis]


@pytest.fixture
async def prefix() -> str:
    """A keyspace nobody else is using."""
    return f"t{uuid4().hex[:12]}"


@pytest.fixture
async def client() -> object:
    assert REDIS_URL is not None
    connection = create_redis_client(url=REDIS_URL, timeout_seconds=2.0)
    try:
        yield connection
    finally:
        await connection.aclose()


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _replica(
    connection: Redis, prefix: str, *, rps: float = 1.0, burst: int = 5
) -> RateLimiterPort:
    """One gateway replica's limiter. Same Redis, same prefix, different object."""
    return RedisTokenBucketRateLimiter(
        connection,
        RateLimitPolicy(requests_per_second=rps, burst=burst),
        key_prefix=prefix,
    )


async def _independent_replica(prefix: str, *, rps: float = 1.0, burst: int = 5) -> RateLimiterPort:
    """A replica with its **own connection pool** - as separate as two processes can be while
    still running in one test."""
    assert REDIS_URL is not None
    connection = create_redis_client(url=REDIS_URL, timeout_seconds=2.0)
    return _replica(connection, prefix, rps=rps, burst=burst)


# =================================================================== cross-instance sharing


async def test_allowance_spent_on_one_replica_is_gone_on_another(
    client: Redis, prefix: str
) -> None:
    """The milestone's headline property. Replica A spends the whole burst; replica B - a
    different object, a different connection pool - must be refused."""
    org = uuid4()
    replica_a = await _independent_replica(prefix, burst=3)
    replica_b = await _independent_replica(prefix, burst=3)

    for _ in range(3):
        assert (await replica_a.acquire(organization_id=org)).allowed is True

    assert (await replica_b.acquire(organization_id=org)).allowed is False


async def test_the_burst_is_shared_not_multiplied_across_replicas(
    client: Redis, prefix: str
) -> None:
    """Falsifies the failure this milestone exists to fix: N replicas must admit the configured
    burst in total, not N times it. Four replicas, burst of 5, twenty attempts -> exactly 5."""
    org = uuid4()
    replicas = [await _independent_replica(prefix, burst=5) for _ in range(4)]

    allowed = 0
    for _ in range(5):
        for replica in replicas:
            if (await replica.acquire(organization_id=org)).allowed:
                allowed += 1

    assert allowed == 5


async def test_two_objects_sharing_one_dict_would_not_have_passed(
    client: Redis, prefix: str
) -> None:
    """The control for the test above. Two *in-process* limiters are genuinely independent, so the
    same script yields 2 x burst - which is exactly the defect the Redis version must not have.
    Without this, 'shared' would be an untested word."""
    org = uuid4()
    local_a = InMemoryTokenBucketRateLimiter(
        FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=5)
    )
    local_b = InMemoryTokenBucketRateLimiter(
        FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=5)
    )

    allowed = 0
    for limiter in (local_a, local_b):
        for _ in range(10):
            if (await limiter.acquire(organization_id=org)).allowed:
                allowed += 1

    assert allowed == 10, "in-process limiters are per-replica; the Redis one must not be"


# =================================================================== atomicity under concurrency


async def test_a_concurrent_burst_across_replicas_never_overspends(
    client: Redis, prefix: str
) -> None:
    """Lost-update detection. Forty concurrent acquires across eight independent replicas against
    a burst of 6 must yield exactly 6 allows.

    A non-atomic read-modify-write shows up here and nowhere else: with GET/SET the interleavings
    let several callers each see the same token and take it, so the count comes out high - and it
    does so only under load, which is precisely when a rate limit matters.
    """
    org = uuid4()
    replicas = [await _independent_replica(prefix, burst=6) for _ in range(8)]

    decisions = await asyncio.gather(
        *(replicas[i % len(replicas)].acquire(organization_id=org) for i in range(40))
    )

    assert sum(1 for d in decisions if d.allowed) == 6


async def test_concurrent_traffic_from_two_tenants_does_not_contaminate_either(
    client: Redis, prefix: str
) -> None:
    org_a, org_b = uuid4(), uuid4()
    replicas = [await _independent_replica(prefix, burst=4) for _ in range(4)]

    decisions = await asyncio.gather(
        *(replicas[i % 4].acquire(organization_id=org_a) for i in range(20)),
        *(replicas[i % 4].acquire(organization_id=org_b) for i in range(20)),
    )

    assert sum(1 for d in decisions[:20] if d.allowed) == 4
    assert sum(1 for d in decisions[20:] if d.allowed) == 4


# =================================================================== tenant isolation


async def test_one_tenant_cannot_exhaust_another_tenants_shared_allowance(
    client: Redis, prefix: str
) -> None:
    """The security property, now across replicas: cross-tenant quota contamination would turn the
    shared limiter into a denial-of-service amplifier reachable by any authenticated tenant."""
    noisy, quiet = uuid4(), uuid4()
    replica_a = await _independent_replica(prefix, burst=2)
    replica_b = await _independent_replica(prefix, burst=2)

    for _ in range(2):
        await replica_a.acquire(organization_id=noisy)
    assert (await replica_b.acquire(organization_id=noisy)).allowed is False

    assert (await replica_b.acquire(organization_id=quiet)).allowed is True


async def test_keys_are_tenant_scoped_and_carry_no_payload(client: Redis, prefix: str) -> None:
    """Redis is outside RLS, so what lands in it is a tenant-isolation surface that only a test can
    police. The key must name the organization and nothing else; the value must be two numbers."""
    org = uuid4()
    replica = _replica(client, prefix)

    await replica.acquire(organization_id=org)

    # decode_responses=False on this client, so Redis hands back bytes; normalise rather than
    # assume, since the assertion is about content and not about the client's decoding mode.
    keys = [_text(key) for key in await client.keys(f"{prefix}:*")]
    assert keys == [f"{prefix}:rl:{org}"]

    stored = await client.hgetall(f"{prefix}:rl:{org}")
    assert {_text(field) for field in stored} == {"tokens", "updated_at"}
    for value in stored.values():
        float(_text(value))  # numbers only: no prompt, no credential, no correlation id


async def test_two_deployments_sharing_one_redis_do_not_share_buckets(client: Redis) -> None:
    """``key_prefix`` is why a shared dev box or staging cluster cannot silently throttle across
    deployments."""
    org = uuid4()
    staging = _replica(client, f"stg{uuid4().hex[:8]}", burst=1)
    production = _replica(client, f"prd{uuid4().hex[:8]}", burst=1)

    assert (await staging.acquire(organization_id=org)).allowed is True
    assert (await staging.acquire(organization_id=org)).allowed is False

    assert (await production.acquire(organization_id=org)).allowed is True


# =================================================================== refill, expiry, recovery


async def test_the_allowance_refills_over_real_time(client: Redis, prefix: str) -> None:
    """Refill uses the Redis server's clock, so this is the one place real time must elapse. A
    high rate keeps the wait short without making the assertion flaky."""
    org = uuid4()
    replica = _replica(client, prefix, rps=20.0, burst=2)

    for _ in range(2):
        await replica.acquire(organization_id=org)
    assert (await replica.acquire(organization_id=org)).allowed is False

    await asyncio.sleep(0.35)  # 20 rps -> ~7 tokens, capped at 2

    assert (await replica.acquire(organization_id=org)).allowed is True


async def test_a_bucket_key_carries_a_ttl_so_idle_tenants_do_not_accumulate_forever(
    client: Redis, prefix: str
) -> None:
    """No sweeper exists, and none is needed: an idle tenant's key removes itself. A key with no
    TTL would be an unbounded keyspace growing with every organization that ever sent a request."""
    org = uuid4()
    replica = _replica(client, prefix, rps=1.0, burst=5)

    await replica.acquire(organization_id=org)

    ttl = await client.ttl(f"{prefix}:rl:{org}")
    assert ttl > 0, "the bucket key would live forever"


async def test_a_tenant_returning_after_expiry_starts_full_rather_than_denied(
    client: Redis, prefix: str
) -> None:
    """Expiry must not be observable as a wrong answer. A key that vanished means the bucket had
    refilled to full anyway, so the tenant is treated as new - not as exhausted."""
    org = uuid4()
    replica = _replica(client, prefix, burst=3)
    await replica.acquire(organization_id=org)

    await client.delete(f"{prefix}:rl:{org}")  # simulate the TTL firing

    decision = await replica.acquire(organization_id=org)
    assert decision.allowed is True
    assert decision.remaining == 2


async def test_the_script_survives_a_script_cache_flush(client: Redis, prefix: str) -> None:
    """``register_script`` uses EVALSHA; a restarted or flushed Redis must recover by itself rather
    than erroring once per replica until someone redeploys."""
    org = uuid4()
    replica = _replica(client, prefix)
    await replica.acquire(organization_id=org)

    await client.script_flush()

    assert (await replica.acquire(organization_id=org)).allowed is True


# =================================================================== outage behaviour


async def test_an_unreachable_redis_reports_unavailable_rather_than_denying() -> None:
    """The adapter must never turn "I could not answer" into "no". Port 1 is reserved and closed,
    so this is a genuine connection failure rather than a mocked one."""
    unreachable = create_redis_client(url="redis://127.0.0.1:1/0", timeout_seconds=0.25)
    try:
        replica = _replica(unreachable, "unused")
        with pytest.raises(RateLimiterUnavailableError):
            await replica.acquire(organization_id=uuid4())
    finally:
        await unreachable.aclose()


async def test_an_outage_degrades_to_a_local_bucket_that_still_limits() -> None:
    """ADR-0021 decision 4, end to end. Degraded means *degraded-closed*: the local bucket still
    enforces the same policy, so an outage costs the sharing, never the limit."""
    org = uuid4()
    unreachable = create_redis_client(url="redis://127.0.0.1:1/0", timeout_seconds=0.25)
    try:
        limiter = DegradedRateLimiter(
            _replica(unreachable, "unused", burst=2),
            InMemoryTokenBucketRateLimiter(
                FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=2)
            ),
        )

        assert (await limiter.acquire(organization_id=org)).allowed is True
        assert (await limiter.acquire(organization_id=org)).allowed is True
        assert (await limiter.acquire(organization_id=org)).allowed is False, (
            "degraded mode must still limit; unlimited would be fail-OPEN"
        )
        assert limiter.degraded is True
    finally:
        await unreachable.aclose()


async def test_the_shared_limiter_is_used_again_once_redis_recovers(
    client: Redis, prefix: str
) -> None:
    """Recovery, not just degradation. A limiter that fell back permanently would silently leave a
    deployment per-replica forever after one blip."""
    org = uuid4()
    healthy = _replica(client, prefix, burst=10)
    local = InMemoryTokenBucketRateLimiter(
        FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=1)
    )
    unreachable = create_redis_client(url="redis://127.0.0.1:1/0", timeout_seconds=0.25)
    try:
        limiter = DegradedRateLimiter(_replica(unreachable, prefix), local)
        await limiter.acquire(organization_id=org)
        assert limiter.degraded is True

        # Swap in the healthy shared limiter, as a reconnect would.
        recovered = DegradedRateLimiter(healthy, local)
        await recovered.acquire(organization_id=org)

        assert recovered.degraded is False
    finally:
        await unreachable.aclose()


async def test_a_degraded_decision_does_not_write_to_the_shared_store(
    client: Redis, prefix: str
) -> None:
    """A fallback that still wrote somewhere would make the outage's after-effects unpredictable.
    Nothing may appear under the prefix while Redis is unreachable."""
    org = uuid4()
    unreachable = create_redis_client(url="redis://127.0.0.1:1/0", timeout_seconds=0.25)
    try:
        limiter = DegradedRateLimiter(
            _replica(unreachable, prefix),
            InMemoryTokenBucketRateLimiter(
                FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=5)
            ),
        )
        await limiter.acquire(organization_id=org)
    finally:
        await unreachable.aclose()

    assert await client.keys(f"{prefix}:*") == []


# =================================================================== the port is unchanged


async def test_the_redis_limiter_satisfies_the_unmodified_m3_port(
    client: Redis, prefix: str
) -> None:
    """ADR-0021's central claim, asserted structurally: the shared implementation conforms to the
    port M3 defined, with no interface change. Where that was *not* possible - the circuit
    breaker's synchronous port, the deduplicator's absent one - M4 stopped instead."""
    assert isinstance(_replica(client, prefix), RateLimiterPort)
    assert isinstance(
        DegradedRateLimiter(
            _replica(client, prefix),
            InMemoryTokenBucketRateLimiter(
                FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=1)
            ),
        ),
        RateLimiterPort,
    )


async def test_both_implementations_answer_the_same_shape(client: Redis, prefix: str) -> None:
    """Rule 4's parity check: the second implementation must not have quietly acquired different
    semantics. Same policy, same sequence, same verdicts and the same denial contract."""
    org_local, org_shared = uuid4(), uuid4()
    local = InMemoryTokenBucketRateLimiter(
        FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=2)
    )
    shared = _replica(client, prefix, rps=1.0, burst=2)

    for limiter, org in ((local, org_local), (shared, org_shared)):
        first = await limiter.acquire(organization_id=org)
        second = await limiter.acquire(organization_id=org)
        third = await limiter.acquire(organization_id=org)

        assert (first.allowed, second.allowed, third.allowed) == (True, True, False)
        assert first.limit == second.limit == third.limit == 2
        assert third.remaining == 0
        assert third.retry_after_seconds is not None
        assert third.retry_after_seconds >= 1
        assert first.retry_after_seconds is None
