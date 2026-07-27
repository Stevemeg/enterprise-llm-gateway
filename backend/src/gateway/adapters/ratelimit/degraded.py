"""Degraded-mode fallback for shared rate limiting (Phase 5 M4, ADR-0021 decision 4).

Wraps a shared limiter with a local one and switches to the local one when the shared store cannot
answer. ``docs/API_Rate_Limiting.md`` §4: "if the rate-limit store is unavailable, the platform
applies a conservative **default cap** (degraded protection) rather than unlimited - a safety bias
consistent with ADR-0009 (protecting the platform), while not blocking all traffic on a soft
control. Hard *budget* remains fail-closed."

## This reverses M3's fail-closed choice, deliberately and only for this control

M3 chose fail-closed and pre-registered the condition for revisiting it: *"the availability cost of
failing closed is approximately zero today, and the day it is not (a shared store, M4) is the day
the trade-off is genuinely different."* With Redis in the path, failing closed turns a blip in the
protective control into a total gateway outage - the control becoming the incident.

**Degraded-closed, not fail-open.** The distinction is the entire justification:

* Traffic is still limited. The local bucket enforces the *same policy*; what is lost is only the
  sharing. For N replicas the effective ceiling during an outage is N x the configured rate -
  bounded and stateable, not unlimited.
* The **financial** control does not degrade. ``ReservationService`` gates every provider call
  against the PostgreSQL ledger and remains fail-closed, so no Redis outage can produce unbounded
  spend. Rate limiting protects infrastructure; the budget protects money; only the former bends.
* It is not silent. Every degraded decision is metered as ``outcome="unavailable"``, and each
  *transition* into or out of degradation is logged once, so "running degraded" is an alertable
  state rather than an invisible one.

## Why a separate class rather than a try/except inside the Redis adapter

The Redis adapter's job is to talk to Redis and report honestly when it cannot; the fail mode is a
policy decision that ADR-0021 may supersede. Keeping them apart means changing the policy later
touches neither the Redis integration nor the middleware, and it keeps the adapter unable to
fabricate an answer it did not receive - which is what makes its own tests meaningful.

## The local bucket is deliberately not kept warm

While Redis is healthy the fallback bucket is untouched, so at the moment of an outage it is full
and a tenant gets one fresh burst before local limiting bites. Mirroring every decision into it
would double the work on the healthy path - the path that must stay cheap - to shave one burst off
a degradation that is already bounded. Recorded as a known, bounded imprecision rather than
engineered away.
"""

from __future__ import annotations

from uuid import UUID

from gateway.application.ports.rate_limit import (
    RateLimitDecision,
    RateLimiterPort,
    RateLimiterUnavailableError,
)
from gateway.observability.logging import get_logger
from gateway.observability.metrics import (
    INGRESS_RATE_LIMIT,
    INGRESS_UNAVAILABLE,
    record_ingress_decision,
)

_logger = get_logger("ratelimit.degraded")


class DegradedRateLimiter:
    """Prefers the shared limiter; falls back to the local one when it cannot answer."""

    def __init__(self, shared: RateLimiterPort, local: RateLimiterPort) -> None:
        self._shared = shared
        self._local = local
        self._degraded = False

    @property
    def degraded(self) -> bool:
        """Whether the last decision came from the local fallback. Read by tests and by the
        readiness surface; never by the middleware, which must treat every decision alike."""
        return self._degraded

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        try:
            decision = await self._shared.acquire(organization_id=organization_id)
        except RateLimiterUnavailableError as exc:
            self._enter_degraded(exc)
            # Counted as "unavailable" rather than as an ordinary allow/deny: the request WAS
            # limited, but by a weaker rule, and an operator needs to see that as its own series.
            record_ingress_decision(control=INGRESS_RATE_LIMIT, outcome=INGRESS_UNAVAILABLE)
            return await self._local.acquire(organization_id=organization_id)
        self._leave_degraded()
        return decision

    def _enter_degraded(self, exc: RateLimiterUnavailableError) -> None:
        if self._degraded:
            return  # already reported; do not log once per request during an outage
        self._degraded = True
        _logger.error(
            "rate_limit_store_degraded",
            reason=type(exc.__cause__ or exc).__name__,
            effect="falling back to a per-replica bucket; the global limit is not enforced",
        )

    def _leave_degraded(self) -> None:
        if not self._degraded:
            return
        self._degraded = False
        _logger.info("rate_limit_store_recovered", effect="the shared limit is enforced again")
