"""Health-tiered routing strategy (ADR-0016 Slice 21) - the Rule-4 first ``RoutingStrategy``.

The one signal this slice has to rank on is the circuit-health tier Slice 20 produces, so the
strategy is exactly that: **prefer a fully healthy provider over a recovering (degraded) one**, and
among equals fall back to a deterministic tiebreak so the choice is reproducible.

## The tiebreak is deterministic on purpose

Within a tier, candidates are ordered by provider name. That is not a quality judgement - it is the
guarantee that two identical candidate sets always produce the same selection, which is what makes
a routing decision explainable and testable (FR-033). A random or first-seen tiebreak would make
the same request route differently on replay, which is precisely the opacity ADR-0012 rejected the
bandit strategy to avoid.

## Why "prefer healthy" and not "only healthy"

A degraded (half-open) provider is deliberately *usable*: its circuit half-opened so that one
request may probe whether it has recovered. Ranking it last rather than excluding it means a
recovering provider carries traffic only when no healthy provider is available - traffic it needs
to close its circuit - without risking it while a healthy alternative exists. Excluding it instead
would leave it half-open forever, never probed, never recovered.

This is not the routing engine and constructs no ``RoutingDecision``: it hands a provider name back
to ``ProviderAgent``, which records the selection into the decision the runtime builds. It is a
pure function of its inputs - no I/O, no clock, no state.
"""

from __future__ import annotations

from collections.abc import Sequence

from gateway.application.ports.routing_strategy import RoutingCandidate, RoutingStrategy


class HealthTieredRoutingStrategy(RoutingStrategy):
    """Selects the healthiest candidate, breaking ties by provider name (deterministic)."""

    def select(self, candidates: Sequence[RoutingCandidate]) -> str | None:
        if not candidates:
            return None
        # Sort key: healthy (degraded=False) before degraded (True), then by name. ``sorted`` is
        # stable, but the name secondary key makes the order total and independent of input order.
        best = min(candidates, key=lambda c: (c.degraded, c.provider))
        return best.provider
