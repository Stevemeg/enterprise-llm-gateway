"""Ingress protection end to end (Phase 5 M3).

These drive the **real composed application** - the real ASGI chain, the real authentication
middleware, the real pipeline, the real routing engine, the real coordinator - reusing
``test_inference_endpoint.Harness`` rather than a hand-built stub. That reuse is the point: "a
rate-limited request performed no downstream work" is only evidence if the components that did not
run are the ones that really would have. The harness already wraps the routing engine, the provider
client and the budget ledger in spies for exactly this purpose.

Every negative case therefore asserts **three** things: the status code, the absence of downstream
side effects, and (where relevant) that the control is still capable of allowing traffic - a
limiter that denied everything would pass a naive "429 was returned" test while being a total
outage.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from gateway.adapters.ratelimit.in_memory_token_bucket import InMemoryTokenBucketRateLimiter
from gateway.application.ports.rate_limit import (
    RateLimitDecision,
    RateLimiterUnavailableError,
    RateLimitPolicy,
)
from gateway.delivery.http.api.inference import INFERENCE_PATH
from tests.unit.test_inference_endpoint import GOOD_TOKEN, Harness

_ONE_MIB = 1_048_576


class SteppingClock:
    def __init__(self) -> None:
        self._moment = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment

    def advance(self, delta: timedelta) -> None:
        self._moment += delta


class BrokenLimiter:
    """A limiter that cannot answer. Models a shared-store outage the in-process bucket cannot
    have, so the middleware's *chosen fail mode* is tested rather than assumed."""

    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        self.calls += 1
        raise RateLimiterUnavailableError("store unreachable")


class CountingLimiter:
    """Records every key it was asked about, so a test can prove *whose* allowance was spent."""

    def __init__(self, *, allow: bool = True) -> None:
        self.keys: list[UUID] = []
        self._allow = allow

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        self.keys.append(organization_id)
        if self._allow:
            return RateLimitDecision(allowed=True, limit=10, remaining=9, reset_seconds=1)
        return RateLimitDecision(
            allowed=False, limit=10, remaining=0, reset_seconds=1, retry_after_seconds=1
        )


def _bucket(clock: SteppingClock, *, rps: float = 1.0, burst: int = 1) -> object:
    return InMemoryTokenBucketRateLimiter(
        clock, RateLimitPolicy(requests_per_second=rps, burst=burst)
    )


# =================================================================== rate limiting


def test_a_request_over_the_limit_is_refused_with_429() -> None:
    harness = Harness(rate_limiter=_bucket(SteppingClock(), burst=1))

    first = harness.post()
    second = harness.post()

    assert first.status_code == 200
    assert second.status_code == 429
    body = second.json()["error"]
    assert body["type"] == "rate_limit_error"
    assert body["code"] == "rate_limited"
    assert body["retryable"] is True


def test_a_rate_limited_request_performs_no_downstream_work_at_all() -> None:
    """The property M3 exists to establish. A 429 must cost nothing: no routing, no agent chain,
    no budget reservation, no provider call - otherwise the limiter protects the bill and not the
    infrastructure, which is half the point."""
    harness = Harness(rate_limiter=_bucket(SteppingClock(), burst=1))
    # The first request is allowed and legitimately does all of this work; the snapshot is what
    # makes the assertions about the *second* request meaningful rather than trivially true.
    harness.post()
    routed_before = list(harness.routing.calls)
    invoked_before = list(harness.client_spy.invocations)
    reserved_before = list(harness.ledger.reserved)
    settled_before = list(harness.ledger.settled)
    assert routed_before, "the baseline did not route"
    assert invoked_before, "the baseline called no provider"
    assert reserved_before, "the baseline reserved no budget"

    assert harness.post().status_code == 429

    assert harness.routing.calls == routed_before, "the routing engine ran for a refused request"
    assert harness.client_spy.invocations == invoked_before, "a provider was called"
    assert harness.ledger.reserved == reserved_before, "budget was reserved"
    assert harness.ledger.settled == settled_before, "budget was settled"


def test_the_429_carries_retry_after_and_ratelimit_headers() -> None:
    """``API_Rate_Limiting.md`` §3. A client that cannot see when to come back can only hammer."""
    harness = Harness(rate_limiter=_bucket(SteppingClock(), burst=1))
    harness.post()

    denied = harness.post()

    assert denied.headers["Retry-After"] == str(denied.json()["error"]["retry_after_seconds"])
    assert "limit=" in denied.headers["RateLimit"]
    assert "remaining=0" in denied.headers["RateLimit"]


def test_a_successful_response_also_advertises_the_remaining_allowance() -> None:
    """§3 requires the header on success too, so a well-behaved client can pace itself instead of
    discovering the limit by hitting it."""
    harness = Harness(rate_limiter=_bucket(SteppingClock(), rps=1.0, burst=5))

    response = harness.post()

    assert response.status_code == 200
    assert "remaining=4" in response.headers["RateLimit"]


def test_the_allowance_recovers_so_the_limiter_is_not_a_permanent_outage() -> None:
    """Falsifies the trivial pass: a limiter that denies forever would satisfy every test above."""
    clock = SteppingClock()
    harness = Harness(rate_limiter=_bucket(clock, rps=1.0, burst=1))
    harness.post()
    assert harness.post().status_code == 429

    clock.advance(timedelta(seconds=2))

    assert harness.post().status_code == 200


def test_the_limit_key_is_the_authenticated_tenant_and_not_a_supplied_header() -> None:
    """The security property: a caller must not be able to nominate whose allowance is spent.

    The request carries a hostile ``X-Organization-Id``; the limiter must still be asked about the
    organization the *credential* resolved to.
    """
    limiter = CountingLimiter()
    harness = Harness(rate_limiter=limiter)
    attacker_supplied = uuid4()

    harness.http.post(
        INFERENCE_PATH,
        json={"prompt": "hello"},
        headers={
            "Authorization": f"Bearer {GOOD_TOKEN}",
            "X-Organization-Id": str(attacker_supplied),
            "X-Tenant-Id": str(attacker_supplied),
        },
    )

    assert limiter.keys, "the limiter was never consulted"
    assert attacker_supplied not in limiter.keys
    from tests.unit.test_inference_endpoint import ORG

    assert limiter.keys == [ORG]


def test_an_unauthenticated_request_is_not_rate_limited_and_still_reaches_nothing() -> None:
    """No verified tenant means no trustworthy key (see the middleware docstring). The request is
    passed through to be refused by the route - which must still cost nothing downstream."""
    limiter = CountingLimiter()
    harness = Harness(rate_limiter=limiter)

    response = harness.post(token=None)

    assert response.status_code == 401
    assert limiter.keys == [], "an unauthenticated request consumed someone's allowance"
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_an_invalid_credential_never_reaches_the_limiter() -> None:
    """Authentication is outside the limiter, so a rejected credential cannot be used to drain a
    tenant's bucket by guessing at it."""
    limiter = CountingLimiter()
    harness = Harness(rate_limiter=limiter)

    assert harness.post(token="not-a-real-token").status_code == 401
    assert limiter.keys == []


def test_a_streaming_request_is_counted_once_at_initiation() -> None:
    """``API_Rate_Limiting.md`` §5: an SSE request counts as **one** request at initiation. Being
    a middleware above the router gives that for free - and the second one is still refused."""
    limiter = CountingLimiter()
    harness = Harness(rate_limiter=limiter)

    with harness.http.stream(
        "POST",
        INFERENCE_PATH,
        json={"prompt": "hello", "stream": True},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    ) as response:
        assert response.status_code == 200
        response.read()

    assert len(limiter.keys) == 1


def test_a_streamed_request_over_the_limit_is_refused_before_the_stream_opens() -> None:
    """The streamed shape must not be a way around the limiter: a 429 here is an ordinary JSON
    error, not a 200 event stream whose first event is a failure."""
    harness = Harness(rate_limiter=_bucket(SteppingClock(), burst=1))
    # Spend the single token on a *streamed* request, so the provider stream - not the unary
    # client - is what the second request must be shown never to reach.
    with harness.http.stream(
        "POST",
        INFERENCE_PATH,
        json={"prompt": "hello", "stream": True},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    ) as first:
        first.read()
    assert first.status_code == 200
    streams_before = len(harness.client.stream_calls)
    assert streams_before == 1, "the baseline opened no provider stream"

    denied = harness.http.post(
        INFERENCE_PATH,
        json={"prompt": "hello", "stream": True},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    )

    assert denied.status_code == 429
    assert denied.headers["content-type"].startswith("application/json")
    assert len(harness.client.stream_calls) == streams_before, "a provider stream was opened"


# ------------------------------------------------------------------ fail mode


def test_a_limiter_that_cannot_answer_fails_closed_with_503() -> None:
    """The chosen fail mode, tested explicitly rather than documented. 503 and not 429: the caller
    exceeded nothing, and no Retry-After was computed by anybody."""
    limiter = BrokenLimiter()
    harness = Harness(rate_limiter=limiter)

    response = harness.post()

    assert response.status_code == 503
    body = response.json()["error"]
    assert body["type"] == "availability_error"
    assert body["code"] == "rate_limit_unavailable"
    assert body["retryable"] is True
    assert limiter.calls == 1


def test_failing_closed_still_performs_no_downstream_work() -> None:
    harness = Harness(rate_limiter=BrokenLimiter())

    assert harness.post().status_code == 503

    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_a_limiter_outage_does_not_leak_its_cause_to_the_caller() -> None:
    """The exception text ("store unreachable") is infrastructure detail. A caller learns that the
    request was not accepted and nothing about why the deployment is unwell."""
    harness = Harness(rate_limiter=BrokenLimiter())

    body = harness.post().json()["error"]["message"]

    assert "store" not in body.lower()
    assert "unreachable" not in body.lower()


# =================================================================== request size limiting


def test_an_oversized_body_is_refused_with_413_before_any_provider_call() -> None:
    harness = Harness(max_body_bytes=512)

    response = harness.http.post(
        INFERENCE_PATH,
        json={"prompt": "x" * 4096},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    )

    assert response.status_code == 413
    body = response.json()["error"]
    assert body["type"] == "invalid_request_error"
    assert body["code"] == "request_too_large"
    assert body["retryable"] is False
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_a_body_within_the_limit_is_served_normally() -> None:
    """Falsifies the trivial pass: a middleware that rejected everything would satisfy the test
    above while being a total outage."""
    harness = Harness(max_body_bytes=_ONE_MIB)

    response = harness.http.post(
        INFERENCE_PATH,
        json={"prompt": "hello"},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    )

    assert response.status_code == 200


def test_an_oversized_body_is_refused_before_authentication_runs() -> None:
    """Placement, asserted behaviourally. The size limiter sits outside authentication, so an
    unauthenticated oversized body is refused with 413 rather than 401 - which means the API-key
    database lookup never happens for a body that was never going to be accepted."""
    harness = Harness(max_body_bytes=512)

    response = harness.http.post(INFERENCE_PATH, json={"prompt": "x" * 4096})

    assert response.status_code == 413


def test_an_oversized_chunked_body_is_refused_even_though_it_declares_no_length() -> None:
    """The path that matters for abuse. Without ``Content-Length`` the declared-size check cannot
    fire, so the running byte count is the only thing standing between the process and an
    unbounded body. A client that under-declares gains nothing for the same reason.
    """
    harness = Harness(max_body_bytes=1024)

    def oversized() -> Iterator[bytes]:
        for _ in range(16):
            yield b"x" * 512

    response = harness.http.post(
        INFERENCE_PATH,
        content=oversized(),
        headers={
            "Authorization": f"Bearer {GOOD_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 413
    assert harness.client_spy.called is False


def test_a_chunked_body_within_the_limit_is_replayed_and_served() -> None:
    """The counting path must not break the request it allows.

    This is the other half of the previous test and the one that would catch a silent regression:
    a middleware that consumed the body to count it and then failed to replay it would still
    return 413 for oversized bodies while breaking every chunked request that was fine.
    """
    harness = Harness(max_body_bytes=_ONE_MIB)

    def small() -> Iterator[bytes]:
        yield b'{"prompt": '
        yield b'"hello"}'

    response = harness.http.post(
        INFERENCE_PATH,
        content=small(),
        headers={
            "Authorization": f"Bearer {GOOD_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200, response.text
    assert harness.client_spy.called is True


def test_an_unparseable_content_length_is_counted_rather_than_trusted() -> None:
    """A malformed declaration must not become a way past the cap. It is treated as *absent*,
    which routes the request into the counting path where the real bytes decide."""
    harness = Harness(max_body_bytes=1024)

    def oversized() -> Iterator[bytes]:
        yield b"x" * 4096

    response = harness.http.post(
        INFERENCE_PATH,
        content=oversized(),
        headers={
            "Authorization": f"Bearer {GOOD_TOKEN}",
            "Content-Type": "application/json",
            "Content-Length": "not-a-number",
        },
    )

    assert response.status_code == 413


def test_a_get_request_with_no_body_is_unaffected() -> None:
    """The limiter must not have an opinion about requests that carry nothing."""
    harness = Harness(max_body_bytes=1)

    assert harness.http.get("/livez").status_code == 200


def test_the_413_message_names_the_cap_but_nothing_tenant_specific() -> None:
    """The cap is a fixed, public property of the deployment; a client that cannot learn it can
    only guess. Nothing else may appear - no path, no tenant, no principal."""
    harness = Harness(max_body_bytes=512)

    message = harness.http.post(
        INFERENCE_PATH,
        json={"prompt": "x" * 4096},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    ).json()["error"]["message"]

    assert "512" in message
    from tests.unit.test_inference_endpoint import ORG, PRINCIPAL

    assert str(ORG) not in message
    assert str(PRINCIPAL) not in message


def test_a_zero_or_negative_cap_is_a_construction_error() -> None:
    from gateway.delivery.http.middleware.body_limit import RequestSizeLimitMiddleware

    async def app(scope: object, receive: object, send: object) -> None:  # pragma: no cover
        return None

    with pytest.raises(ValueError, match="max_bytes"):
        RequestSizeLimitMiddleware(app, max_bytes=0)


# =================================================================== both controls composed


def test_both_controls_are_in_the_chain_at_once_and_the_cheaper_one_wins() -> None:
    """Ordering, asserted behaviourally: an oversized body from a tenant who is *also* over its
    rate limit is refused 413, because the size check runs outside the limiter. The limiter is
    never consulted, which is what makes it the cheaper gate."""
    limiter = CountingLimiter(allow=False)
    harness = Harness(rate_limiter=limiter, max_body_bytes=512)

    response = harness.http.post(
        INFERENCE_PATH,
        json={"prompt": "x" * 4096},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    )

    assert response.status_code == 413
    assert limiter.keys == [], "the rate limiter ran for a body that was already too large"


def test_a_normal_request_passes_both_controls_and_is_served() -> None:
    harness = Harness(rate_limiter=_bucket(SteppingClock(), burst=5), max_body_bytes=_ONE_MIB)

    response = harness.post()

    assert response.status_code == 200
    assert harness.client_spy.called is True


def test_the_ingress_refusals_carry_a_request_id_proving_context_runs_outermost() -> None:
    """Both new refusals are produced by middleware, so both must still be correlatable - which
    only holds if RequestContextMiddleware is outside both of them."""
    rate_limited = Harness(rate_limiter=_bucket(SteppingClock(), burst=1))
    rate_limited.post()
    denied = rate_limited.post()

    too_large = Harness(max_body_bytes=512)
    oversized = too_large.http.post(
        INFERENCE_PATH,
        json={"prompt": "x" * 4096},
        headers={"Authorization": f"Bearer {GOOD_TOKEN}"},
    )

    for response in (denied, oversized):
        request_id = response.json()["error"]["request_id"]
        assert request_id != "unknown"
        assert response.headers["X-Request-Id"] == request_id


def test_the_chain_without_ingress_protection_is_unchanged() -> None:
    """M3 is additive. A deployment or test that wires neither control gets exactly the pre-M3
    chain, so nothing about this milestone can silently change the unprotected path's behaviour."""
    harness = Harness()

    response = harness.post()

    assert response.status_code == 200
    assert "RateLimit" not in response.headers
