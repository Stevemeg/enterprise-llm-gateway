"""Evaluation seam (ADR-0016 Slice 12) - a **capability-owned** port, not a Tier-1 protocol.

ADR-0016 demoted Evaluation from Tier 1 on the claim that it can consume the stable execution
seams without every interface needing to know evaluation exists. This slice tests that claim, and
it holds: nothing in ``RoutingDecision``, ``RoutingExecution``, ``PipelineStage``, ``BaseAgent``,
``ToolRegistry``, ``McpGateway``, ``ProviderResponse`` or ``InferenceRequest`` changed to make
evaluation possible. Rule 5 was not triggered against Tier 1 *or* against any capability-owned
port - evaluation reads only facts those seams already publish.

## Evaluation observes; it never participates

An evaluator is handed a completed outcome and returns a verdict. It has no route to the provider,
the budget ledger, the cache, the router or the retry loop - structurally, not merely by
convention: ``gateway.application.evaluation`` cannot import any of them (import-linter, Slice 12).
An evaluator therefore *cannot* change the response its caller already received, because by the
time it runs there is nothing left to change.

## Why this is not a ``PipelineStage``

``PipelineStage`` is Tier 1 and unchanged, and evaluation deliberately does not implement it. Two
reasons, both concrete rather than stylistic:

1. **Evaluation is post-hoc, not interception.** It needs the *finished* execution result -
   outcome, response, usage. A stage's ``after_response`` would have to smuggle that through
   ``StageContext.attributes``, which is typed ``dict[str, Any]`` and documented as opaque by
   contract. Passing a rich typed result through an untyped bag would convert a checked contract
   into a convention, which is exactly what Rule 3 exists to prevent.
2. **No pipeline runner exists yet.** Nothing in this codebase executes a chain of stages around an
   inference. Implementing ``PipelineStage`` today would produce an abstraction with no executor -
   a seam consumed by nothing (Rule 4).

The stage seam remains available and untouched for capabilities that genuinely intercept a request
in flight - which is precisely what Slice 13's policy stage does.

## Result vocabulary: four states, because three of them would lie

"The evaluator failed" and "the thing being evaluated failed" are different operational facts, and
collapsing them into a boolean makes a broken evaluator indistinguishable from a broken response.
``NOT_APPLICABLE`` is the fourth, and it is not padding: both first evaluators genuinely need to
say "this outcome is outside what I judge" (a budget denial delivered no response to assess), and
reporting that as ``PASSED`` would inflate quality metrics with requests nobody evaluated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from gateway.application.execution.inference_coordinator import ExecutionOutcome
from gateway.application.ports.providers import ProviderResponse


class EvaluationOutcome(StrEnum):
    """How one evaluator's verdict came out (closed vocabulary, safe as a metric label).

    ``ERROR`` is the evaluator faulting - never the target failing. Keeping them apart is the
    whole point: a dashboard that cannot tell "10% of responses are bad" from "10% of evaluations
    crashed" reports the same number for a quality problem and an outage.
    """

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class EvaluationInput:
    """The completed inference facts an evaluator may inspect.

    Deliberately narrow (Rule 5). It carries no ``RoutingDecision``, no ``CostRecord``, no attempt
    history and no request payload, because no evaluator in this slice consumes any of them -
    adding them "because an evaluator might want them later" is the speculative-field accumulation
    Rule 5 exists to prevent, and a request payload specifically is prompt data this capability has
    no reason to hold.

    ``organization_id``/``correlation_id`` are consumed by ``EvaluationRunner`` to scope and
    identify the report, not by the evaluators themselves.
    """

    organization_id: UUID
    correlation_id: str
    outcome: ExecutionOutcome
    response: ProviderResponse


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """One evaluator's verdict on one inference.

    ``detail`` is mandatory for ``FAILED`` and ``ERROR``: a verdict that says something went wrong
    without saying what is not actionable, the same reason ``StageResult`` requires a reason for
    ``BLOCK`` and ``RoutingDecision`` requires non-empty ``reasoning_steps``.
    """

    evaluator: str
    outcome: EvaluationOutcome
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.evaluator:
            raise ValueError("EvaluationResult.evaluator must identify the evaluator")
        if self.outcome in (EvaluationOutcome.FAILED, EvaluationOutcome.ERROR) and not self.detail:
            raise ValueError(
                f"an {self.outcome.value!r} result must carry a detail explaining it "
                f"(evaluator={self.evaluator!r})"
            )


@runtime_checkable
class Evaluator(Protocol):
    """Judges one completed inference. Must never raise for a verdict - return ``FAILED``.

    ``async`` for consistency with every other port in this codebase (``ProviderClient``,
    ``PermissionResolver``, ``BaseAgent``, ``ResponseCachePort``): both implementations here are
    pure and synchronous, but a port that is sync cannot later accommodate an evaluator that reads
    anything without a breaking signature change, and the cost of ``async`` on a pure function is
    nil.
    """

    @property
    def name(self) -> str:
        """Stable identifier, used in results and metrics."""
        ...

    async def evaluate(self, target: EvaluationInput) -> EvaluationResult:
        """Return a verdict. Raising is a defect, not a verdict - ``EvaluationRunner`` converts an
        escaped exception into an ``ERROR`` result so one broken evaluator cannot erase the rest."""
        ...
