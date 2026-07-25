"""Routing-strategy seam (ADR-0016 Slice 21, realizing ADR-0012's ``RoutingStrategyPort``) - a
**capability-owned** port, not a Tier-1 protocol.

Slices 6-20 selected a provider by taking the first usable candidate. That was correct while every
usable candidate was interchangeable, but Slice 20 made them *not* interchangeable: a candidate
may now be fully healthy (a closed circuit) or merely recovering (a half-open circuit being
probed). Once candidates differ, "the first one" is a decision nobody made. Adaptive routing is
the decision - it *ranks* the usable candidates and selects the best - and this port is where that
ranking lives so it can be swapped without touching the agent that consumes it.

## Why a port and not just logic inside ProviderAgent

ADR-0012 chose "a pipeline of composable strategies ... each strategy behind a
``RoutingStrategyPort``" precisely so a new ranking rule is a new adapter, not a change to the
selection agent (open/closed, NFR-M02). The ML/bandit strategy that ADR-0012 explicitly deferred
"to preserve explainability and governance" becomes one more implementation behind this same port
if it is ever built - it is not this slice, and this port does not presuppose it.

## What a strategy may and may not decide

A strategy ranks the candidates it is **given** and returns one of them (or ``None`` if the set is
empty). It does not fetch candidates, call a provider, price a call, or consult a budget - those
belong to the catalog, the executor, the cost agent and the reservation service respectively. It
sees only ``RoutingCandidate`` values and must be a pure, deterministic function of them: the same
candidates in the same order must always yield the same choice, so a routing decision is
reproducible and explainable (FR-033).

## Why ``RoutingCandidate`` carries only ``degraded``

The single signal this slice's consumer ranks on is the circuit-health tier Slice 20 produces:
healthy (closed) versus degraded (half-open). Latency, cost and quality-tier signals are real
future ranking inputs (ADR-0012's ``lowest_latency`` / ``lowest_cost`` / ``quality_tier``), and
this dataclass deliberately does **not** carry them yet - nothing ranks on them (the cost agent is
still a stub, and no per-candidate latency signal is exposed). Adding them now would be the
speculative field Rule 5 forbids; the strategy that consumes them is when they arrive.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RoutingCandidate:
    """One provider the strategy may choose, with the ranking signal it is judged on.

    ``degraded`` is the health tier: ``False`` is a fully healthy provider (closed circuit),
    ``True`` a recovering one (half-open circuit) that is usable but should be preferred last.
    """

    provider: str
    degraded: bool = False


@runtime_checkable
class RoutingStrategy(Protocol):
    """Ranks usable candidates and selects one (ADR-0012 ranking strategy)."""

    def select(self, candidates: Sequence[RoutingCandidate]) -> str | None:
        """Return the chosen provider's name, or ``None`` for an empty candidate set.

        Must be pure and deterministic: identical input must always yield identical output, so the
        selection recorded in a ``RoutingDecision`` is reproducible.
        """
        ...
