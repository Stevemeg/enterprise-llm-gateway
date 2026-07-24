"""RequestPipeline - the executor for the Tier-1 stage seam (ADR-0016 invariant 5, Slice 14).

ADR-0016 defines invariant 5 as "stage protocol (inspect/annotate/block/continue)" with CI
enforcement "**stage registration + ordering** + protocol tests". The protocol has existed since
Slice 1 and three real stages now implement it, but **nothing has ever executed one**: registration
and ordering were never built. Every stage written between Slices 5 and 13 was therefore
enforced-by-construction and unenforced-in-traffic, which the evidence log records as the single
largest piece of outstanding debt across those slices. This module is the missing half.

A stage that exists but never runs is not a control. That is the entire point of this slice.

## What this class owns, and what it deliberately does not

It owns **which stages run, in what order, and what a verdict means**. It owns nothing else, and
structurally cannot: this package imports ``application.ports.pipeline`` and nothing else from the
codebase (import-linter, Slice 14). It cannot route, authorize, evaluate policy, reserve budget,
call a provider or retry - it only asks each stage in turn and obeys the answer. A runner that
could also *decide* would become a second authorizer sitting above the stages, which is exactly the
duplicated ownership these seams exist to prevent.

## Fail closed, in four distinct ways

An admission chain that admits on doubt is not an admission chain. The runner therefore refuses in
every case where a stage did not clearly say "continue":

1. **BLOCK** - the ordinary path. Remaining stages do not run (see below).
2. **A stage raises** - a crashed control has not admitted anything. The exception is recorded in
   the stage's audit annotations rather than swallowed, and never reaches the caller as a 500 in
   place of a decision.
3. **A stage returns something that is not a ``StageResult``** - ``PipelineStage`` is
   ``runtime_checkable``, so conformance is structural and a stage can be wired in whose
   ``before_request`` returns the wrong type entirely. "Unexpected" must not resolve to "allowed",
   the same reasoning ``PolicyStage`` applies to a malformed engine verdict.
4. **A stage blocks without a reason** - see the finding below.

## Finding: ``StageResult`` documents an invariant it does not enforce

``StageResult``'s own docstring states that ``BLOCK`` must carry a ``reason``, because "a stage that
blocks without saying why produces an unexplainable denial". The dataclass has no ``__post_init__``
and does not check it. Until this slice nothing executed a stage, so nothing could observe the gap.

**It is fixed here, in the consumer, and not in the Tier-1 type** - a deliberate Rule 5 outcome
rather than an oversight. Rule 5's third question asks why a change does not belong in the consumer
instead, and here it plainly does: the runner is the only component that ever reads a
``StageResult``, so compensating here closes the gap completely, while adding validation to a frozen
Tier-1 type would invalidate previously-legal constructions across three slices of existing stages
for no additional guarantee. An unexplained block is still a block - it is substituted with the
generic reason and flagged ``unexplained_block`` for the audit trail, never upgraded to admission.

## Ordering: first block wins, and the rest of the chain does not run

Once a stage blocks, no later stage's ``before_request`` is called. Two reasons, both concrete:

* **Side effects.** ``AgentRoutingStage`` invokes the routing engine, which runs the whole agent
  chain. Continuing past a denial in order to "collect all the reasons" would mean an unauthorized
  request still causing routing to execute - the precise bypass this slice exists to close.
* **Audit honesty.** A chain that kept going would record verdicts for a request that was already
  refused, and those verdicts describe a request nobody ever admitted.

## Stages do not communicate through the context

Each stage receives its own copy of ``StageContext.attributes``. A stage therefore cannot alter what
a later stage sees, and one stage's annotations never silently become another stage's input.

This is stricter than it needs to be for today's three stages (none reads another's output) and it
is chosen deliberately: ``attributes`` is opaque by contract and caller-supplied, so a shared
mutable bag would let a stage - or a caller crafting an attribute that looks like a stage's
annotation - influence a control that runs after it. Annotations are returned in the per-stage
audit record instead, where they cannot be confused with request input. When a control genuinely
needs an earlier control's output, that dependency should be an explicit typed collaborator, not a
key two components happen to agree on (Rule 3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from gateway.application.ports.pipeline import (
    PipelineStage,
    StageAction,
    StageContext,
    StageResult,
)

#: What a caller is told when the runner itself refuses. Stage-authored denials keep their own
#: reason (the stages already decide what is safe to disclose); this covers only the cases where
#: no usable reason exists, and it names no stage, rule or threshold.
GENERIC_BLOCK_REASON = "request was not admitted"


@dataclass(frozen=True, slots=True)
class StageRecord:
    """What one stage decided about one request - the admission trail's unit.

    Analogous to ``ReasoningStep`` for routing and ``AttemptRecord`` for reflection, and kept
    per-stage for the same reason those are: ``annotations`` from different stages collide on
    common keys (every stage emits ``stage``; both RBAC and policy emit their own ``rule``-shaped
    detail), so a single merged bag would silently overwrite one control's audit with another's.
    """

    stage: str
    action: StageAction
    reason: str | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.action is StageAction.BLOCK


@dataclass(frozen=True, slots=True)
class AdmissionOutcome:
    """Whether a request may proceed, and the complete record of how that was decided.

    ``records`` is never empty and a block always names both the stage and a reason: an admission
    decision nobody can explain is the same failure ``RoutingDecision.reasoning_steps`` and
    ``StageResult``'s BLOCK contract each exist to prevent.

    ``admitted`` is derived from ``blocked_by`` rather than stored, so there is exactly one
    representation of the decision. A separate boolean could disagree with the records, and the
    two would eventually drift.
    """

    records: tuple[StageRecord, ...]
    blocked_by: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.records:
            raise ValueError("an AdmissionOutcome must record at least one stage")
        if self.blocked_by is not None and not self.reason:
            raise ValueError(f"stage {self.blocked_by!r} blocked without a reason")
        if self.blocked_by is None and self.reason is not None:
            raise ValueError("an admitted request cannot carry a block reason")

    @property
    def admitted(self) -> bool:
        return self.blocked_by is None

    @property
    def stages_run(self) -> tuple[str, ...]:
        """The stages that actually executed, in order. Shorter than the chain when one blocked."""
        return tuple(record.stage for record in self.records)


class RequestPipeline:
    """Runs a fixed, ordered chain of stages over one request and reports whether it is admitted."""

    def __init__(self, stages: Sequence[PipelineStage]) -> None:
        if not stages:
            # An empty chain would admit everything while looking like a configured pipeline -
            # silence that reads as approval. Same refusal as ``EvaluationRunner`` with no
            # evaluators and ``AgentRuntime`` with no agents, and here the consequence is a
            # request path with no admission control at all.
            raise ValueError("RequestPipeline requires at least one stage")

        # Names are resolved once, at registration. A stage whose ``name`` property later returned
        # something else would otherwise make its own audit records untraceable.
        names = tuple(stage.name for stage in stages)
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            # Two stages answering to one name make the trail ambiguous: "blocked by policy" would
            # no longer identify which control refused, and a metric keyed on the name would sum
            # two different decisions.
            raise ValueError(f"stage names must be unique; duplicated: {', '.join(duplicates)}")

        self._stages = tuple(zip(names, stages, strict=True))

    @property
    def stage_names(self) -> tuple[str, ...]:
        """The registered chain, in execution order."""
        return tuple(name for name, _ in self._stages)

    async def admit(self, context: StageContext) -> AdmissionOutcome:
        """Run ``before_request`` down the chain, stopping at the first stage that blocks.

        Never raises for a stage-level failure: every refusal, including a defective stage, comes
        back as a recorded block. The pipeline holds no per-request state, so concurrent calls
        cannot observe one another.
        """
        records: list[StageRecord] = []
        for name, stage in self._stages:
            record = await self._run(name, stage, context)
            records.append(record)
            if record.blocked:
                return AdmissionOutcome(
                    records=tuple(records), blocked_by=record.stage, reason=record.reason
                )
        return AdmissionOutcome(records=tuple(records))

    @staticmethod
    async def _run(name: str, stage: PipelineStage, context: StageContext) -> StageRecord:
        """Execute one stage and normalise whatever it did into a record. Fails closed."""
        # Each stage sees its own copy of the attributes bag - see the module docstring.
        private = replace(context, attributes=dict(context.attributes))
        try:
            result = await stage.before_request(private)
        except Exception as exc:
            # Deliberately broad. A control that crashed has not admitted the request, and letting
            # the exception propagate would replace a decision with a stack trace.
            return StageRecord(
                stage=name,
                action=StageAction.BLOCK,
                reason=GENERIC_BLOCK_REASON,
                annotations={
                    "stage": name,
                    "stage_error": True,
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            )

        if not isinstance(result, StageResult):
            return StageRecord(
                stage=name,
                action=StageAction.BLOCK,
                reason=GENERIC_BLOCK_REASON,
                annotations={
                    "stage": name,
                    "malformed_result": True,
                    "detail": f"stage returned {type(result).__name__}",
                },
            )

        if result.action is StageAction.BLOCK and not result.reason:
            # StageResult documents that BLOCK carries a reason but does not enforce it; see the
            # module docstring. The block stands - only the explanation is substituted.
            return StageRecord(
                stage=name,
                action=StageAction.BLOCK,
                reason=GENERIC_BLOCK_REASON,
                annotations={"stage": name, "unexplained_block": True, **result.annotations},
            )

        return StageRecord(
            stage=name,
            action=result.action,
            reason=result.reason,
            annotations=dict(result.annotations),
        )
