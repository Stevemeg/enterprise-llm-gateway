"""UsageAccountingConsistencyEvaluator (ADR-0016 Slice 12).

Answers: **does this outcome's usage match what the accounting rules require of it?**

This is the more interesting of the two first evaluators, because the invariant it checks is one
the money path already silently depends on, in *opposite directions* depending on how the response
was produced:

* A genuinely **executed** success must carry ``ProviderUsage``. ``CostAccountant.account()``
  raises ``MissingUsageError`` without it, and ``ReservationService.settle()`` cannot convert the
  reservation into recorded spend - so a delivered success with no usage means either an
  unsettled reservation still holding budget, or spend that was never booked.
* A **cache hit** must carry no usage at all. Nothing was sent to a provider, so no tokens were
  observed; Slice 10 sets ``usage=None`` deliberately, on the grounds that fabricating usage for a
  call that never happened would misrepresent an observation. Usage appearing on a hit would mean
  the cache had begun inventing consumption - and any metering built on it would over-bill.

Both directions are load-bearing today, and neither has an automated check anywhere else. That is
what makes this a useful first evaluator rather than a demonstration: it observes an existing
production invariant using existing data, and needed no new field to do it (Rule 5).

Deterministic, pure, no I/O, no model.
"""

from __future__ import annotations

from gateway.application.ports.evaluation import (
    EvaluationInput,
    EvaluationOutcome,
    EvaluationResult,
)
from gateway.application.ports.execution import ExecutionOutcome


class UsageAccountingConsistencyEvaluator:
    """Executed successes must report usage; cache hits must not."""

    def __init__(self, name: str = "usage_accounting_consistency") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def evaluate(self, target: EvaluationInput) -> EvaluationResult:
        if target.outcome is ExecutionOutcome.CACHE_HIT:
            if target.response.usage is not None:
                return EvaluationResult(
                    evaluator=self._name,
                    outcome=EvaluationOutcome.FAILED,
                    detail="cache hit reported provider usage, but no provider was called",
                )
            return EvaluationResult(
                evaluator=self._name,
                outcome=EvaluationOutcome.PASSED,
                detail="cache hit correctly reported no usage",
            )

        if target.outcome is ExecutionOutcome.EXECUTED and target.response.ok:
            if target.response.usage is None:
                return EvaluationResult(
                    evaluator=self._name,
                    outcome=EvaluationOutcome.FAILED,
                    detail="executed success reported no usage, so its cost cannot be settled",
                )
            return EvaluationResult(
                evaluator=self._name,
                outcome=EvaluationOutcome.PASSED,
                detail="executed success reported usage available for settlement",
            )

        return EvaluationResult(
            evaluator=self._name,
            outcome=EvaluationOutcome.NOT_APPLICABLE,
            detail=f"no billable execution occurred (outcome={target.outcome.value})",
        )
