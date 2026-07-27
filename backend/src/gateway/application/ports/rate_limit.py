"""Ingress rate-limiting seam (Phase 5 M3, realizing FR-064/065 and ``docs/API_Rate_Limiting.md``)
- a **capability-owned** port, not a Tier-1 protocol.

Tier 1 is untouched and Rule 5 is not triggered against any existing protocol: nothing about
counting a tenant's requests changes ``RoutingDecision``, ``PipelineStage``, ``BaseAgent``,
``McpGatewayPort`` or ``ToolRegistryPort``. This port is born under Rule 2 on the same footing as
``PermissionResolver`` (Slice 5), ``ProviderClient`` (Slice 7), ``PricingPort`` (Slice 8),
``CircuitBreaker`` (Slice 20), ``RoutingStrategy`` (Slice 21) and ``StreamingProviderClient``
(M1) - a capability introducing its own typed port, none of which shipped an ADR.

## Why this is a port at all, rather than a dict inside the middleware

Two reasons, both structural rather than stylistic:

* **The decision is not an HTTP concern.** "Has this tenant spent its allowance" is a policy
  question with a state machine, a clock and a tenant key. Delivery translates that verdict into
  ``429`` + ``Retry-After``; it must not *make* it, or the delivery layer acquires an application
  responsibility - the one thing ``delivery/http/api/inference.py`` is written to avoid.
* **The state must be single-instanced.** A component that built its own limiter would count a
  fraction of the traffic and let the rest through, silently, with every test still green. That is
  the same defect the circuit-breaker and deduplicator construction guards exist to prevent, and it
  is guarded the same way.

## Why ``acquire`` is ``async`` when the first implementation needs no I/O

Not speculation, and not Rule-5 growth - this is the shape chosen at birth, with two pieces of
evidence in hand:

1. ``docs/API_Rate_Limiting.md`` §4 is an **accepted external specification** and it decides the
   mechanism: "Token-bucket in Redis (atomic), evaluated at the edge/API tier". A limiter whose
   decided target is a network round-trip cannot be born synchronous.
2. This repository already ran the experiment. ``CircuitBreaker.observe``/``assess`` were declared
   synchronous with an explicit "No I/O in the contract" rationale; that choice is precisely what
   now stands between the breaker and a cross-replica implementation. Repeating it here, one
   milestone before the distributed-state milestone, would be choosing to relearn it.

The only consumer is an ASGI middleware whose ``dispatch`` is already a coroutine, so ``async``
costs it nothing.

## Fail mode is the caller's, and it is deliberate

``RateLimiterUnavailableError`` exists so a limiter that cannot answer says so instead of guessing.
It is **not** raised by the in-process implementation - process memory has no outage mode distinct
from the process itself - and it is not invented to fake one. It types the boundary a shared-store
implementation will need, and it lets the middleware's chosen fail mode be stated and tested now
rather than discovered later. That mode is **closed** (see ``middleware/rate_limit.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID


class RateLimiterUnavailableError(RuntimeError):
    """The limiter could not reach the state it needs to decide.

    Distinct from "denied": a denial is an answer, this is the absence of one. Collapsing them
    would make a limiter outage indistinguishable from a tenant genuinely over its allowance, and
    the two demand different responses (``429`` with a real ``Retry-After`` versus a fail-closed
    ``503`` a client must not treat as its own fault).
    """


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """How much traffic one scope may send: a sustained rate plus a burst allowance.

    A typed object rather than two loose numbers (Rule 3) - the same reasoning
    ``CircuitBreakerConfig`` and ``RetryPolicy`` use. Both values are limits a future per-tenant
    policy will want to vary, and an untyped pair would let a caller transpose them silently.

    ``burst`` is the bucket's capacity, so it is also the largest instantaneous spike allowed;
    ``requests_per_second`` is the refill rate, so it is the sustained ceiling.
    """

    requests_per_second: float
    burst: int

    def __post_init__(self) -> None:
        if self.requests_per_second <= 0:
            raise ValueError(
                f"requests_per_second must be > 0, got {self.requests_per_second}; "
                "a non-positive rate would deny every request forever rather than limit them"
            )
        if self.burst < 1:
            raise ValueError(
                f"burst must be >= 1, got {self.burst}; "
                "a bucket that cannot hold one token denies the very first request"
            )


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """One limiter verdict, carrying everything ``docs/API_Rate_Limiting.md`` §3 must signal.

    The numbers are part of the contract, not diagnostics: §3 requires a ``RateLimit`` header on
    **success** responses too, so an allowed decision must report its remaining allowance. Making
    the delivery layer recompute them from the policy would put the limiter's arithmetic in two
    places, which is exactly how a header and a verdict start disagreeing.
    """

    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.allowed and self.retry_after_seconds is not None:
            raise ValueError("an allowed decision must not carry retry guidance")
        if not self.allowed and self.retry_after_seconds is None:
            raise ValueError(
                "a denial must say when to retry: API_Rate_Limiting.md §3 requires Retry-After "
                "on a 429, and a client told only 'no' can only guess or hammer"
            )


@runtime_checkable
class RateLimiterPort(Protocol):
    """Decides whether one more request may proceed for a tenant, and consumes the allowance.

    A ``Protocol`` for the same reason ``CircuitBreaker`` is: the middleware depends on this shape,
    the composition root injects the single instance, and a shared-store implementation slots in as
    a Rule-4 second implementation without touching the consumer.
    """

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        """Attempt to spend one unit of ``organization_id``'s allowance.

        **Mutating, not a query** - hence ``acquire`` rather than ``check``. An allowed decision
        has already consumed the unit; a denial consumes nothing, so a rejected flood cannot push
        a tenant's recovery further away the harder it pushes.

        The tenant key must come from authenticated identity. Implementations never see a header
        or a request body, so a caller cannot nominate whose allowance to spend.

        Raises:
            RateLimiterUnavailableError: the limiter cannot reach its state. Never raised to mean
                "denied" - the caller's fail mode depends on telling those apart.
        """
        ...
