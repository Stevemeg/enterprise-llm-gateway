"""Pricing seam (ADR-0016 Slice 8) - a **capability-owned** port, not a Tier-1 protocol.

Answers exactly one question: what does this provider/model cost per 1000 tokens, in which
currency, for this tenant.

Only input/output token pricing exists because only input/output tokens are consumed anywhere in
this project. Cached-token, image, audio and tool-call pricing are real provider dimensions this
port deliberately does not model - adding them now would be speculative generality with no
consumer (Rule 5).

## Rule 5 event (Slice 19): ``organization_id`` added to ``price_for``

**Active consumers:** ``application/accounting/cost_accountant.py`` and
``application/accounting/reservation_service.py``. Both already hold ``organization_id`` at the
call site - it is a parameter of the very methods that call ``price_for`` - so the change
propagates no new data through any layer.

**Why the existing protocol was insufficient:** Slice 8 recorded the reason this parameter was
*absent* and the precise condition for adding it: "``docs/Schema.sql``'s `price_table` documents
`organization_id` for future negotiated pricing, but nothing in this slice consumes tenant-scoped
pricing, so ``price_for`` stays global (Rule 5: no active consumer needs the tenant dimension
yet)." Slice 19 is that consumer. ``price_table.organization_id`` is ``NOT NULL`` and the table is
RLS-scoped, so a durable pricing adapter cannot read a single row without a tenant. A global
signature would have forced either an unscoped read (impossible under RLS, and wrong if it were
possible) or a second, narrower table duplicating one that already fits - the option ADR-0017 took
for budgets only because those Phase-1 tables carried genuinely unused dimensions and an
incompatible identity type. Neither applies here: the *only* dimension `price_table` adds is the
tenant, and that dimension is required, not surplus.

**Why the change does not belong in the consumer instead:** pricing per tenant is a property of
the price list, not of the caller. A consumer that filtered a global price list by tenant would be
re-implementing the row-level scoping the storage layer already enforces, in a place with no
access to the negotiated rates (FR-074/075) the column exists for.

This is a **capability-owned** port, so this is a Rule 5 event recorded in the evidence log - not a
Tier-1 change and not a new ADR. ``StaticPriceTable`` keeps its global behaviour by ignoring the
argument, which is correct for a deployment-level price list and is documented there.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Price per 1000 tokens for one provider/model, in one currency."""

    provider: str
    model: str
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal
    currency: str


@runtime_checkable
class PricingPort(Protocol):
    """Resolves the current price for a provider/model pair."""

    async def price_for(
        self, provider: str, model: str, *, organization_id: UUID
    ) -> ModelPrice | None:
        """Current price for this tenant, or ``None`` if this provider/model has no configured
        price.

        ``None`` is not a business outcome - the caller must treat an unpriced model as a
        configuration defect (``UnknownPriceError``), never as ordinary zero cost.
        """
        ...
