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

## Rule 5 event (Phase 5 M2): ``NOT_ACCOUNTABLE`` added

**Active consumer:** ``delivery/http/api/inference.py`` - it must choose an HTTP status, and it
had no way to express "the gateway refused because it could not account for this call". The
condition therefore escaped as an uncaught ``UnknownPriceError`` and surfaced as a **generic 500**:
an operator saw an unexplained server fault, and a caller saw an unexplained server fault, for what
is in fact a deliberate fail-closed refusal caused by a missing price-table row.

**Why the existing vocabulary was insufficient:** every other member is either "it ran" or a
*named* reason it did not. Reusing ``BUDGET_DENIED`` would tell a tenant they were out of money
when they were not; reusing ``NOT_ROUTED`` would blame routing for a decision routing made
correctly. Both would be the delivery layer reading a fabricated cause.

**Why the change does not belong in the consumer instead:** the delivery layer cannot import
``application.accounting`` (import-linter, Slice 17), so it structurally cannot catch the
accounting exception and classify it itself - and it should not, because "was this call
accountable" is decided where the call is coordinated, not where its result is rendered.

Capability-owned vocabulary, so this is a Rule 5 event recorded in the evidence log, not a new
ADR. Additive: every existing member and every existing consumer branch is unchanged.
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
    #: The gateway could not price or account for this call, so it refused to serve it - an
    #: unpriced provider/model before the call, or usage the provider never reported after it.
    #: A **configuration or provider defect**, never a statement about the tenant's budget, and
    #: deliberately one member rather than two: the caller must not learn which, and the operator
    #: learns which from the log line and the metric, not from the response.
    NOT_ACCOUNTABLE = "not_accountable"
