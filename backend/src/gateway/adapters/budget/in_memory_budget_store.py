"""Single-process, in-memory BudgetPort (ADR-0016 Slice 8, Rule 4).

## Documented limitations (not omissions)

- **Not atomic.** ``snapshot`` and ``record`` are two separate awaits; nothing serializes them
  against concurrent callers. This does not provide hard concurrency-safe enforcement (ADR-0004
  rejected exactly this shape as the sole hot-path mechanism). It provides deterministic
  accounting of already-incurred cost.
- **Not durable.** State is a process-local dict. Restarting the process forgets all spend and
  all applied idempotency keys.
- **Not distributed.** Multiple gateway replicas would each keep their own independent totals.

This is deliberately the only implementation this slice ships, mirroring the pricing adapter - no
independence contract exists between budget adapters because there is only one.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from uuid import UUID

from gateway.application.ports.budget import BudgetPort, BudgetSnapshot, BudgetUnavailableError
from gateway.application.ports.money import Money


class InMemoryBudgetStore(BudgetPort):
    """Org-scoped hard budgets, held entirely in process memory."""

    def __init__(
        self, limits: Mapping[UUID, Money] | None = None, *, unavailable: bool = False
    ) -> None:
        self._limits: dict[UUID, Money] = dict(limits or {})
        self._spent: dict[UUID, Money] = {}
        self._applied_keys: dict[UUID, set[str]] = {}
        # A construction-time toggle to simulate a store outage in tests - there is no real
        # infrastructure here to actually fail.
        self._unavailable = unavailable

    async def snapshot(self, organization_id: UUID) -> BudgetSnapshot | None:
        if self._unavailable:
            raise BudgetUnavailableError("simulated budget store outage")
        limit = self._limits.get(organization_id)
        if limit is None:
            return None
        spent = self._spent.get(organization_id, Money(Decimal(0), limit.currency))
        return BudgetSnapshot(organization_id=organization_id, limit=limit, spent=spent)

    async def record(self, organization_id: UUID, cost: Money, *, idempotency_key: str) -> None:
        if self._unavailable:
            raise BudgetUnavailableError("simulated budget store outage")
        applied = self._applied_keys.setdefault(organization_id, set())
        if idempotency_key in applied:
            # Already recorded under this key - a retried accounting call must not charge twice.
            return
        applied.add(idempotency_key)
        current = self._spent.get(organization_id)
        self._spent[organization_id] = cost if current is None else current + cost
