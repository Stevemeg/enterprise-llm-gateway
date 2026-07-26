"""ReservationReconciler - reclaims budget holds whose owner is gone (Phase 5 M2).

## The debt this closes

Slice 9 made reserve/settle/release atomic and durable, and left one hole its own evidence record
named: **the release only happens if the process lives long enough to run it.** A crash, a killed
pod, a hard task cancellation between ``reserve`` and ``settle`` leaves the row ``reserved`` and
the money held forever. Nothing in Phase 4 could ever return it, so a crash-looping deployment
silently ate a tenant's budget - a denial of service that no error, log or metric reported, because
from the ledger's point of view nothing went wrong.

## What "expired" means here, and why there is no ``expires_at`` column

A hold is stale when it has been ``reserved`` for longer than ``ttl``. That is **age**, and age is
already recorded: ``budget_reservation.created_at`` (migration 0006), with ``reservation_status``
already carrying an ``expired`` member (migration 0001). So this milestone adds **no migration**.

An ``expires_at`` column was considered and rejected: it would always equal
``created_at + ttl`` for one deployment-wide ``ttl``, so it is derived data, and storing derived
data lets the copy disagree with the rule the moment the rule changes (Rule 3). A *per-request*
expiry would not be derived - but nothing sets a per-request timeout today, so the column would
have a writer of one constant and no reader that varied. That is a column added because a future
schema mentions one, which is exactly what this phase forbids.

## Why the TTL must be generous, not tight

Reclaiming a hold that is still live would let the tenant reserve the same money twice and
overspend - a *worse* failure than the leak. The TTL is therefore an upper bound on how long a
legitimate request can hold a reservation, not a tuning knob for how fast leaks are cleaned up.
The default (15 minutes) is far beyond any request this gateway can currently produce: a provider
call is bounded by ``ProviderConnection.timeout_seconds`` (30s by default) and reflection makes at
most three of them.

## Who calls this, and the honest operational story

There is **no scheduler in this system**, and M2 does not invent one - an eventing platform or a
background-worker framework introduced here would be infrastructure with no owner. Instead the
reconciler is a plain callable, and its production consumer is ``ReservationService.reserve``: the
sweep runs for **the tenant that is about to reserve**, at the one moment stale holds actually
matter, because they are reducing that tenant's headroom right now.

That choice has three properties worth stating plainly:

* **It is tenant-scoped, so it is RLS-safe by construction.** A cross-tenant sweep would need to
  see every organization's rows, which ``app_rw`` cannot do (ADR-0014) and which would need a new
  ``SECURITY DEFINER`` function and its own ADR (ADR-0019's standing rule). Nothing here needs one.
* **It cannot rot.** A callable that only a future cron job invokes is untested code pretending to
  be a safety net. This one runs on every reservation, so if it breaks, everything breaks loudly.
* **It costs one extra statement per reservation.** That is a real price, stated rather than
  hidden. It is one indexed ``UPDATE`` against
  ``ix_budget_reservation_org_status``, and it usually matches nothing.

A tenant that stops sending traffic entirely keeps its leaked holds until it sends another
request. That is the documented limitation of self-scheduling, and the reason this class is a
separately callable service rather than an inlined branch: when a scheduled worker acquires an
owner (Phase 5 M4/M5), it calls exactly this, and nothing else changes.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from gateway.application.ports.ledger import BudgetLedgerPort, LedgerUnavailableError
from gateway.observability.logging import get_logger
from gateway.shared.clock import Clock

_logger = get_logger("accounting")

#: How long a hold may legitimately stay ``reserved``. See the module docstring: this is an upper
#: bound on request duration, not a cleanup interval.
DEFAULT_RESERVATION_TTL = timedelta(minutes=15)


class ReservationReconciler:
    """Returns one tenant's abandoned budget holds. Owns the staleness rule and nothing else."""

    def __init__(self, ledger: BudgetLedgerPort, clock: Clock, ttl: timedelta) -> None:
        if ttl <= timedelta(0):
            raise ValueError(f"reservation TTL must be positive, got {ttl}")
        self._ledger = ledger
        self._clock = clock
        self._ttl = ttl

    async def reclaim(self, organization_id: UUID) -> int:
        """Reclaim this tenant's expired holds, returning how many. Never raises into a caller.

        A ledger outage is swallowed **deliberately**, and it is the one place in the accounting
        layer where that is right: this is a repair, not a decision. Failing the caller's request
        because a cleanup could not run would turn a stale row into a refused inference - strictly
        worse than leaving the row for the next attempt, and the opposite of ADR-0009 row 1's
        intent (that rule fails closed to prevent *unbounded spend*; skipping a reclaim can only
        ever leave the tenant with *less* headroom, never more).
        """
        cutoff = self._clock.now() - self._ttl
        try:
            reclaimed = await self._ledger.reconcile_expired(organization_id, older_than=cutoff)
        except LedgerUnavailableError:
            _logger.warning(
                "reservation_reconcile_unavailable", organization_id=str(organization_id)
            )
            return 0
        if reclaimed:
            # Never routine. Every reclaimed hold is a request that died mid-flight, so this is
            # the signal an operator needs to notice crash-looping - it must not be a debug line.
            _logger.warning(
                "reservations_reclaimed",
                organization_id=str(organization_id),
                reclaimed=reclaimed,
                ttl_seconds=int(self._ttl.total_seconds()),
            )
        return reclaimed
