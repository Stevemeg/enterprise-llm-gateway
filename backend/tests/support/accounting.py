"""Test helper for building a ``ReservationService`` (Phase 5 M2).

``ReservationService`` gained a fourth collaborator in M2 - the reconciler whose sweep runs before
every reservation. Most tests do not care about reconciliation and only need a service that
behaves as it always did, so they build one here rather than repeating the wiring.

The default TTL is deliberately **huge**. A test that reserves and then settles within the same
millisecond must not have its own live hold reclaimed underneath it; reconciliation behaviour is
asserted by the tests that ask for it explicitly (``tests/unit/test_reservation_reconciler.py``
and ``tests/integration/test_reservation_reconciliation_postgres.py``), which pass a real clock
and a real TTL. A helper that quietly made every other test reconciliation-sensitive would be a
helper that hides the very thing M2 added.
"""

from __future__ import annotations

from datetime import timedelta

from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_reconciler import ReservationReconciler
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.pricing import PricingPort
from gateway.shared.clock import Clock, SystemClock

#: Long enough that no hold taken during a test run can ever be considered stale.
INERT_TTL = timedelta(days=365)


def reservation_service(
    ledger: BudgetLedgerPort,
    pricing: PricingPort,
    *,
    clock: Clock | None = None,
    ttl: timedelta = INERT_TTL,
) -> ReservationService:
    """A ``ReservationService`` whose reconciler never reclaims anything, unless asked to."""
    return ReservationService(
        ledger,
        pricing,
        CostAccountant(pricing),
        ReservationReconciler(ledger, clock or SystemClock(), ttl),
    )
