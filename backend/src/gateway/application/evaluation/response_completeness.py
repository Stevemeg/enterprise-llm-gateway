"""ResponseCompletenessEvaluator (ADR-0016 Slice 12).

Answers one question: **when this gateway reported success, did it actually deliver something?**

Deterministic, pure, no I/O, no model. It reads only facts ``ProviderResponse`` already publishes,
so it needed no protocol change to exist (Rule 5). It is not a quality judge - it cannot tell a
good answer from a bad one, and deliberately does not try. It catches the specific failure where a
response is marked ``ok`` while carrying nothing, which is a real defect class in this codebase:
``ProviderResponse.content`` is typed ``Any`` with a ``None`` default, so a client adapter can
construct a "successful" empty response without any type error - and Slice 10 would then cache it,
and Slice 9 would settle real money against it.

## Why a failed provider call is NOT_APPLICABLE rather than FAILED

A provider failure is already recorded, explained and acted on by ``ExecutionOutcome`` and the
retry classifier. An evaluator that restated it as ``FAILED`` would add no information and would
double-count one incident in any metric built on both. This evaluator judges delivered successes;
everything else is outside its scope, and saying so is more honest than a verdict it did not form.
"""

from __future__ import annotations

from gateway.application.execution.inference_coordinator import ExecutionOutcome
from gateway.application.ports.evaluation import (
    EvaluationInput,
    EvaluationOutcome,
    EvaluationResult,
)

_DELIVERING_OUTCOMES = (ExecutionOutcome.EXECUTED, ExecutionOutcome.CACHE_HIT)


class ResponseCompletenessEvaluator:
    """A response reported as successful must carry content."""

    def __init__(self, name: str = "response_completeness") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, target: EvaluationInput) -> EvaluationResult:
        if target.outcome not in _DELIVERING_OUTCOMES or not target.response.ok:
            return EvaluationResult(
                evaluator=self._name,
                outcome=EvaluationOutcome.NOT_APPLICABLE,
                detail=f"no successful response was delivered (outcome={target.outcome.value})",
            )
        if target.response.content is None:
            return EvaluationResult(
                evaluator=self._name,
                outcome=EvaluationOutcome.FAILED,
                detail="response reported ok=True but carried no content",
            )
        return EvaluationResult(
            evaluator=self._name,
            outcome=EvaluationOutcome.PASSED,
            detail="successful response carried content",
        )
