"""Circuit-breaker seam (ADR-0016 Slice 20, realizing ADR-0012 / FR-037-038) - a
**capability-owned** port, not a Tier-1 protocol.

Tier 1 is untouched (Rule 5 not triggered): ``RoutingDecision`` and ``HealthDecision`` already
carry everything routing needs to *express* health - ``healthy_candidates`` /
``degraded_candidates`` / ``excluded_candidates`` have existed since Slice 6. What was missing is a
component that *knows* which providers are currently failing, so the ``HealthAgent`` stub could
stop treating every candidate as healthy. This port is that knowledge, and it is capability-owned
for the same reason ``PermissionResolver`` and ``PricingPort`` are: it answers one capability's
question ("is this provider's circuit open"), not a concern every interface must share.

## Why the state is a port and not just a field on something

Two components need it, at two different moments, and they must agree:

* the **HealthAgent** reads it at routing time to exclude open circuits (a *read*, before the call);
* the **execution coordinator** feeds it call outcomes at settlement time (a *write*, after the
  call).

A shared, injected object with a typed contract keeps those two honest - the reader and the writer
cannot drift, and neither can accidentally construct its own copy of the state (a construction
guard enforces the single instance, exactly as it does for permission resolvers).

## What a circuit outcome is, and is not

``observe`` takes ``ProviderCallResult``, which distinguishes three things the breaker treats
differently:

* a **success** - the provider served the request (moves a half-open circuit toward closed);
* a **transient provider fault** (``TRANSIENT_PROVIDER_ERROR_CATEGORIES`` - timeout, rate-limit,
  server error) - the provider failed *of its own health* (moves a circuit toward open);
* **anything else** - a malformed or misauthenticated request, or an unclassified failure. These
  are *ignored*: they would recur against any provider and say nothing about this one, so counting
  them would let a caller's bad requests trip a healthy provider's breaker. This is the same
  set reflection uses to decide retryability, shared from ``ports.providers`` so the two cannot
  disagree (Rule 3).

## No I/O in the contract

``observe`` and ``assess`` are synchronous and side-effect-free beyond the in-memory state they
maintain. A circuit breaker must react within one call's latency budget (NFR-P01), which a
per-call database round-trip cannot meet - the live authoritative state is in-process by design
(ADR-0012: "maintained from passive live errors/latency"). Durable cross-replica snapshots
(``provider_health``) are deliberately deferred: they need the eventing backbone (ADR-0005,
unimplemented) to be a shared source of truth, and writing snapshots nothing reads would be the
speculative infrastructure Rule 8 forbids.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from gateway.application.ports.providers import ProviderErrorCategory


class CircuitState(StrEnum):
    """The state of one provider's circuit (mirrors the ``health_state`` enum in Schema.sql).

    ``DEGRADED`` from the schema is not modelled: it is a continuous-health notion (a provider that
    is up but slow), and nothing consumes a "slow but working" signal yet (Rule 8). The three
    states here are the classic breaker triad and are all that circuit *breaking* requires.
    """

    CLOSED = "closed"  # healthy: requests flow normally
    OPEN = "open"  # tripped: excluded from routing until the cooldown elapses
    HALF_OPEN = "half_open"  # cooldown elapsed: one probe is allowed through to test recovery


@dataclass(frozen=True, slots=True)
class ProviderCallResult:
    """The outcome of one provider call, in the terms the breaker acts on.

    ``ok`` is success. When not ``ok``, ``error_category`` decides whether the failure counts
    against the provider's health (transient fault) or is ignored (client-side / unclassified).
    """

    ok: bool
    error_category: ProviderErrorCategory | None = None


@dataclass(frozen=True, slots=True)
class ProviderCircuit:
    """One provider's current circuit state, as the HealthAgent reads it."""

    provider: str
    state: CircuitState


@runtime_checkable
class CircuitBreaker(Protocol):
    """Records provider-call outcomes and reports each provider's circuit state.

    A ``Protocol`` for the same reason ``PermissionResolver`` is: consumers depend on this shape,
    the composition root injects the one implementation (a construction guard keeps it single), and
    a future durable/shared breaker - if ADR-0005 ever makes cross-replica sharing real - slots in
    as a Rule-4 second implementation without touching a consumer.
    """

    def observe(self, *, organization_id: UUID, provider: str, result: ProviderCallResult) -> None:
        """Feed one call's outcome into this provider's circuit for this tenant."""
        ...

    def assess(
        self, *, organization_id: UUID, providers: Sequence[str]
    ) -> tuple[ProviderCircuit, ...]:
        """Report the current circuit state of each named provider for this tenant.

        Pure with respect to *routing* - but it may perform the time-driven ``OPEN -> HALF_OPEN``
        transition (the cooldown has elapsed, so the next request is allowed to probe). A provider
        never seen before is reported ``CLOSED``: absence of evidence is not evidence of failure,
        and a brand-new provider must be usable.
        """
        ...
