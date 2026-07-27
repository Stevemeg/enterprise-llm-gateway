"""Per-tenant ingress rate limiting (Phase 5 M3, FR-064/065, ``docs/API_Rate_Limiting.md``).

Runs **inside** ``AuthenticationMiddleware`` and **outside** every route, which is the only
position that satisfies both of its constraints at once:

* it needs a *verified* tenant, and ``request.state.auth`` does not exist until authentication has
  run - so it cannot be outermost;
* it must refuse before any expensive work, and everything expensive (RBAC's database lookup, the
  policy engine, five routing agents, the cache lookup, the budget reservation, the provider call)
  lives in the route - so it cannot be a route dependency that runs alongside them.

``docs/API_Rate_Limiting.md`` §1 requires "rate limit is checked before budget reservation (cheap
gate first)"; being a middleware layer above the router satisfies that structurally, not by
convention. A rejected request never calls ``InferenceService``, so no reservation, provider call,
settlement or cache write can follow - the same argument ``InferenceService`` makes about admission
denial, one layer further out.

## The limit key is the authenticated tenant, and nothing else

``organization_id`` comes from ``AuthenticationContext``, which the authentication middleware built
from a verified credential. **No header, query parameter or body field is consulted.** Accepting a
caller-supplied tenant hint would let anyone spend a competitor's allowance (denial of service by
attribution) or mint an unlimited supply of fresh buckets by varying the hint - and it would put
attacker-controlled text into a limiter key.

## An unauthenticated request is passed through, deliberately

Without ``request.state.auth`` there is no trustworthy scope to limit on. The alternatives were
weighed and rejected:

* **Limit by client IP.** ``request.client.host`` is the immediate peer, which behind any proxy is
  the proxy; ``X-Forwarded-For`` is caller-supplied and forgeable unless a trusted-proxy chain is
  configured, which this deployment has no configuration for. Keying a limiter on a forgeable value
  lets an attacker both evade the limit (rotate the header) and deny others (borrow their value).
  Building the trusted-proxy machinery to fix that is a real capability with no evidence demanding
  it in this milestone.
* **Refuse everything unauthenticated.** That is the route's job already, and it would 429 the
  liveness and readiness probes.

So volumetric protection for *unauthenticated* traffic stays where this project's own architecture
already puts it: ``System_Context.md`` assigns "TLS, WAF, rate limit, DDoS" to the Z0→Z1 edge. What
is *not* deferred is the cost of an unauthenticated flood inside this process, and it is bounded:
such a request reaches at most the authenticator and is refused with a 401. Recorded as a
limitation in the evidence log rather than closed with a mechanism that would be worse than the gap.

## Fail mode: CLOSED, chosen rather than defaulted

If the limiter cannot answer (``RateLimiterUnavailableError``) the request is refused with 503.

``docs/API_Rate_Limiting.md`` §4 anticipates a *shared store* outage and prefers a "conservative
default cap" over both extremes. That option is not available to this implementation and pretending
otherwise would be fiction: the only limiter here is process memory, whose sole failure mode is a
programming defect, and a degraded cap served from the same broken component is not a fallback.

Fail-closed is therefore chosen for three reasons, none of them "it is the safe-sounding default":

1. The plan's M3 objective states the intent in as many words - ingress protection is to be
   "fail-closed and cardinality-bounded".
2. Fail-open here has a specific cost this project has already named as its recurring failure mode:
   a protection control that silently stops protecting while every check stays green. A defect that
   disables the limiter would be invisible in traffic and visible only in a bill.
3. Fail-open's usual justification - "do not let a flaky network dependency take down the service" -
   does not apply to an in-process limiter, which has no network dependency to flake. The
   availability cost of failing closed is therefore approximately zero *today*, and the day it is
   not (a shared store, M4) is the day the trade-off is genuinely different and must be re-decided
   with the evidence then available.

This choice forces no ADR: ADR-0009's stated bias is that protective controls fail closed, and the
plan records that only *fail-open* would have required one.

**503, not 429.** A limiter outage is not the caller's fault and its allowance is unknown; ``429``
would tell a client it exceeded a limit that was never measured, and ``Retry-After`` would be a
number nobody computed. ``availability_error`` is the honest category, matching the ledger-outage
precedent (``budget_unavailable``) exactly.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway.application.ports.rate_limit import (
    RateLimitDecision,
    RateLimiterPort,
    RateLimiterUnavailableError,
)
from gateway.observability.logging import get_logger
from gateway.observability.metrics import (
    INGRESS_ALLOWED,
    INGRESS_DENIED,
    INGRESS_RATE_LIMIT,
    INGRESS_UNAVAILABLE,
    record_ingress_decision,
)

#: ``docs/API_Rate_Limiting.md`` §3. One header carrying the triple, not three headers: the draft
#: IETF field this mirrors is a structured single value, and emitting three would invent a dialect.
_RATELIMIT_HEADER = "RateLimit"
_RETRY_AFTER_HEADER = "Retry-After"

_logger = get_logger("http.ratelimit")


def _rate_limit_value(decision: RateLimitDecision) -> str:
    return f"limit={decision.limit}, remaining={decision.remaining}, reset={decision.reset_seconds}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Spends one unit of the authenticated tenant's allowance, or refuses the request."""

    def __init__(self, app: object, *, limiter: RateLimiterPort) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        auth = getattr(request.state, "auth", None)
        if auth is None:
            # No verified tenant, so nothing trustworthy to key on (see the module docstring).
            return await call_next(request)

        request_id: str = getattr(request.state, "request_id", "unknown")
        try:
            decision = await self._limiter.acquire(organization_id=auth.organization_id)
        except RateLimiterUnavailableError:
            record_ingress_decision(control=INGRESS_RATE_LIMIT, outcome=INGRESS_UNAVAILABLE)
            # No tenant id in the log line either: the reason is the fact worth recording, and an
            # outage affects every tenant identically.
            _logger.error("rate_limiter_unavailable", request_id=request_id)
            return JSONResponse(
                {
                    "error": {
                        "type": "availability_error",
                        "code": "rate_limit_unavailable",
                        "message": "Request rate could not be verified, so the request was "
                        "not accepted.",
                        "request_id": request_id,
                        "retryable": True,
                    }
                },
                status_code=503,
            )

        if not decision.allowed:
            record_ingress_decision(control=INGRESS_RATE_LIMIT, outcome=INGRESS_DENIED)
            assert decision.retry_after_seconds is not None  # RateLimitDecision enforces this
            return JSONResponse(
                {
                    "error": {
                        "type": "rate_limit_error",
                        "code": "rate_limited",
                        "message": "Too many requests. Retry after the indicated delay.",
                        "request_id": request_id,
                        "retryable": True,
                        "retry_after_seconds": decision.retry_after_seconds,
                    }
                },
                status_code=429,
                headers={
                    _RETRY_AFTER_HEADER: str(decision.retry_after_seconds),
                    _RATELIMIT_HEADER: _rate_limit_value(decision),
                },
            )

        record_ingress_decision(control=INGRESS_RATE_LIMIT, outcome=INGRESS_ALLOWED)
        response = await call_next(request)
        # §3: successful responses advertise the remaining allowance too, so a well-behaved client
        # can pace itself instead of discovering the limit by hitting it.
        response.headers[_RATELIMIT_HEADER] = _rate_limit_value(decision)
        return response
