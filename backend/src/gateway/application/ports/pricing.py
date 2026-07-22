"""Pricing seam (ADR-0016 Slice 8) - a **capability-owned** port, not a Tier-1 protocol.

Answers exactly one question: what does this provider/model cost per 1000 tokens, in which
currency. No live provider pricing APIs, no historical price versioning, no per-tenant negotiated
rates - ``docs/Schema.sql``'s `price_table` documents `organization_id` for future negotiated
pricing, but nothing in this slice consumes tenant-scoped pricing, so ``price_for`` stays global
(Rule 5: no active consumer needs the tenant dimension yet).

Only input/output token pricing exists because only input/output tokens are consumed anywhere in
this slice. Cached-token, image, audio and tool-call pricing are real provider dimensions this
port deliberately does not model - adding them now would be speculative generality with no
consumer (Rule 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable


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

    async def price_for(self, provider: str, model: str) -> ModelPrice | None:
        """Current price, or ``None`` if this provider/model has no configured price.

        ``None`` is not a business outcome - the caller must treat an unpriced model as a
        configuration defect (``UnknownPriceError``), never as ordinary zero cost.
        """
        ...
