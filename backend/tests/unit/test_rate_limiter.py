"""The token-bucket limiter itself (Phase 5 M3), tested failure-first.

The limiter is the only component in the ingress chain that holds state, so these tests are about
the three things state gets wrong: it refills incorrectly, it leaks between tenants, or it lets a
denied caller make its own situation worse.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from gateway.adapters.ratelimit.in_memory_token_bucket import InMemoryTokenBucketRateLimiter
from gateway.application.ports.rate_limit import (
    RateLimitDecision,
    RateLimiterPort,
    RateLimitPolicy,
)

ORG_A = uuid4()
ORG_B = uuid4()


class SteppingClock:
    """A clock the test moves deliberately, matching ``test_circuit_breaker.py``'s convention.

    Local rather than shared: refill is the behaviour under test here, so the ability to move time
    belongs to this module. It accepts a ``timedelta`` (including a negative one) because one test
    needs to prove a backwards NTP step cannot mint tokens.
    """

    def __init__(self) -> None:
        self._moment = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> None:
        self._moment += delta


def _limiter(clock: SteppingClock, *, rps: float = 1.0, burst: int = 2) -> RateLimiterPort:
    return InMemoryTokenBucketRateLimiter(
        clock, RateLimitPolicy(requests_per_second=rps, burst=burst)
    )


# ------------------------------------------------------------------ the limit actually limits


async def test_a_burst_is_allowed_and_the_next_request_is_denied() -> None:
    """The failure-first case: exhausting the bucket must produce a denial, not a warning."""
    limiter = _limiter(SteppingClock(), burst=2)

    first = await limiter.acquire(organization_id=ORG_A)
    second = await limiter.acquire(organization_id=ORG_A)
    third = await limiter.acquire(organization_id=ORG_A)

    assert (first.allowed, second.allowed) == (True, True)
    assert third.allowed is False
    assert third.remaining == 0


async def test_a_denial_carries_retry_guidance_a_client_can_obey() -> None:
    """``Retry-After: 0`` would be an instruction to hammer; the contract forbids it."""
    limiter = _limiter(SteppingClock(), rps=1.0, burst=1)

    await limiter.acquire(organization_id=ORG_A)
    denied = await limiter.acquire(organization_id=ORG_A)

    assert denied.allowed is False
    assert denied.retry_after_seconds is not None
    assert denied.retry_after_seconds >= 1


async def test_waiting_the_advertised_delay_actually_succeeds() -> None:
    """Retry-After must not be optimistic: obeying it has to work, or it teaches clients to ignore
    it. Rounding *up* is what makes this hold."""
    clock = SteppingClock()
    limiter = _limiter(clock, rps=1.0, burst=1)

    await limiter.acquire(organization_id=ORG_A)
    denied = await limiter.acquire(organization_id=ORG_A)
    assert denied.retry_after_seconds is not None

    clock.advance(timedelta(seconds=denied.retry_after_seconds))

    assert (await limiter.acquire(organization_id=ORG_A)).allowed is True


async def test_a_denied_request_consumes_nothing_so_hammering_cannot_delay_recovery() -> None:
    """If a denial spent a token, a client retrying in a tight loop would push its own recovery
    permanently out of reach - a self-inflicted outage the limiter caused."""
    clock = SteppingClock()
    limiter = _limiter(clock, rps=1.0, burst=1)
    await limiter.acquire(organization_id=ORG_A)

    for _ in range(50):
        assert (await limiter.acquire(organization_id=ORG_A)).allowed is False

    clock.advance(timedelta(seconds=1))

    assert (await limiter.acquire(organization_id=ORG_A)).allowed is True


# ------------------------------------------------------------------ refill behaviour


async def test_tokens_refill_at_the_configured_rate() -> None:
    clock = SteppingClock()
    limiter = _limiter(clock, rps=2.0, burst=4)
    for _ in range(4):
        assert (await limiter.acquire(organization_id=ORG_A)).allowed is True
    assert (await limiter.acquire(organization_id=ORG_A)).allowed is False

    clock.advance(timedelta(seconds=1))  # 2 rps -> 2 tokens back

    assert (await limiter.acquire(organization_id=ORG_A)).allowed is True
    assert (await limiter.acquire(organization_id=ORG_A)).allowed is True
    assert (await limiter.acquire(organization_id=ORG_A)).allowed is False


async def test_refill_is_capped_at_the_burst_so_idle_time_does_not_bank_credit() -> None:
    """A tenant idle for an hour must not then be able to fire an hour's worth of requests at
    once - that is precisely the spike the bucket exists to smooth."""
    clock = SteppingClock()
    limiter = _limiter(clock, rps=1.0, burst=3)

    clock.advance(timedelta(hours=1))

    allowed = 0
    for _ in range(100):
        if (await limiter.acquire(organization_id=ORG_A)).allowed:
            allowed += 1
    assert allowed == 3


async def test_a_backwards_clock_step_never_grants_tokens() -> None:
    """Wall-clock time can step backwards (NTP). The safe direction for a protective control is to
    lose a little refill, never to mint an unbounded amount of it."""
    clock = SteppingClock()
    limiter = _limiter(clock, rps=1.0, burst=2)
    await limiter.acquire(organization_id=ORG_A)
    await limiter.acquire(organization_id=ORG_A)

    clock.advance(timedelta(seconds=-3600))

    assert (await limiter.acquire(organization_id=ORG_A)).allowed is False


# ------------------------------------------------------------------ tenant isolation


async def test_one_tenant_cannot_exhaust_another_tenants_allowance() -> None:
    """Cross-tenant quota contamination is the security property here, not a nicety: a noisy
    neighbour that could deny others turns the limiter into a denial-of-service amplifier."""
    limiter = _limiter(SteppingClock(), rps=1.0, burst=1)

    await limiter.acquire(organization_id=ORG_A)
    assert (await limiter.acquire(organization_id=ORG_A)).allowed is False

    assert (await limiter.acquire(organization_id=ORG_B)).allowed is True


async def test_a_tenants_exhaustion_does_not_follow_it_to_another_tenant_key() -> None:
    """The inverse direction: B's bucket must not be *created* already spent by A's traffic."""
    clock = SteppingClock()
    limiter = _limiter(clock, rps=1.0, burst=5)
    for _ in range(5):
        await limiter.acquire(organization_id=ORG_A)

    for _ in range(5):
        assert (await limiter.acquire(organization_id=ORG_B)).allowed is True


# ------------------------------------------------------------------ concurrency


async def test_a_concurrent_burst_respects_the_limit_within_one_node() -> None:
    """Twenty coroutines racing for five tokens must yield exactly five allows.

    ``acquire`` contains no ``await`` between reading and writing a bucket, so it is atomic with
    respect to other tasks on the same loop; this asserts that rather than assuming it. A lost
    update would show up here as six or more allows.
    """
    limiter = _limiter(SteppingClock(), rps=1.0, burst=5)

    decisions = await asyncio.gather(*(limiter.acquire(organization_id=ORG_A) for _ in range(20)))

    assert sum(1 for d in decisions if d.allowed) == 5


async def test_concurrent_bursts_from_two_tenants_do_not_contaminate_each_other() -> None:
    limiter = _limiter(SteppingClock(), rps=1.0, burst=3)

    decisions = await asyncio.gather(
        *(limiter.acquire(organization_id=ORG_A) for _ in range(10)),
        *(limiter.acquire(organization_id=ORG_B) for _ in range(10)),
    )
    allowed_a = sum(1 for d in decisions[:10] if d.allowed)
    allowed_b = sum(1 for d in decisions[10:] if d.allowed)

    assert (allowed_a, allowed_b) == (3, 3)


# ------------------------------------------------------------------ contract validation


def test_the_port_rejects_a_policy_that_could_never_allow_anything() -> None:
    with pytest.raises(ValueError, match="requests_per_second"):
        RateLimitPolicy(requests_per_second=0, burst=5)
    with pytest.raises(ValueError, match="burst"):
        RateLimitPolicy(requests_per_second=1, burst=0)


def test_a_denial_without_retry_guidance_is_not_constructible() -> None:
    """API_Rate_Limiting.md §3 requires Retry-After on a 429. Typing it makes forgetting it a
    construction error rather than a header a client silently never receives."""
    with pytest.raises(ValueError, match="when to retry"):
        RateLimitDecision(allowed=False, limit=5, remaining=0, reset_seconds=1)


def test_an_allowed_decision_cannot_smuggle_retry_guidance() -> None:
    with pytest.raises(ValueError, match="must not carry retry guidance"):
        RateLimitDecision(
            allowed=True, limit=5, remaining=4, reset_seconds=1, retry_after_seconds=3
        )


def test_the_in_memory_limiter_satisfies_the_port() -> None:
    assert isinstance(_limiter(SteppingClock()), RateLimiterPort)
