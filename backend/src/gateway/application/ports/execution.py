"""Execution-outcome vocabulary (ADR-0016 Slice 10; relocated here in Slice 16).

``ExecutionOutcome`` is the closed vocabulary describing how one coordinated execution ended. It
is shared by ``InferenceCoordinator`` (which produces it), the evaluation port and both evaluators
(which read it), ``InferenceService`` and the request-path metrics.

## Why it moved out of ``inference_coordinator.py``

It was defined inside the concrete orchestrator, which made every consumer - including
``ports/evaluation.py`` - import an orchestrator just to name a vocabulary. A **port** depending
on a concrete application service inverts the dependency direction the ports layer exists to
establish, and it was the one outcome enum in the codebase placed that way: ``ReservationOutcome``
lives in ``ports/ledger.py``, ``ProviderErrorCategory`` in ``ports/providers.py``,
``EvaluationOutcome`` in ``ports/evaluation.py`` and ``StageAction`` in ``ports/pipeline.py``.

The inversion was latent until Slice 16 instrumented the coordinator: the moment the orchestrator
imported ``observability.metrics``, the pre-existing edge transitively dragged ``prometheus_client``
into ``gateway.application.ports`` and broke "ports declare contracts only (no transport or
framework)". The contract was correct and the placement was not, so the placement changed - the
alternative would have been to weaken a contract to accommodate a misplaced type.

**This is a relocation, not a protocol change.** No member was added, removed or renamed and no
semantics changed, so Rule 5 is not triggered; it is a defect in prior-slice code that this
slice's first real integration exposed.
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionOutcome(StrEnum):
    """Closed vocabulary for how one coordinated execution ended (safe as a metric label,
    mirrors ``RoutingOutcome``)."""

    CACHE_HIT = "cache_hit"
    EXECUTED = "executed"
    NOT_ROUTED = "not_routed"
    BUDGET_DENIED = "budget_denied"
    BUDGET_UNAVAILABLE = "budget_unavailable"
