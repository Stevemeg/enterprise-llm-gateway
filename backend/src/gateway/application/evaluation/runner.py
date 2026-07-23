"""EvaluationRunner - runs a fixed evaluator chain over one completed inference
(ADR-0016 Slice 12).

Not a port: like ``ProviderExecutor``, ``CostAccountant``, ``ReservationService``,
``InferenceCoordinator`` and ``ReflectiveExecutor``, this is a concrete orchestrator composed in
the composition root, which is why it is the thing the construction guard confines rather than a
seam with implementations.

## Fail-open toward delivery, never silent

Evaluation runs *after* the caller already has its response, so it structurally cannot fail an
inference - there is no request left to fail. But "cannot break delivery" must not become "quietly
swallows problems": an evaluator that raises is recorded as an ``ERROR`` result naming the
evaluator and the exception, and the chain continues. One broken evaluator therefore degrades
exactly its own verdict and nothing else, which is the property
``test_one_evaluator_erroring_does_not_erase_the_others`` pins down.

Ordering is the declared order, always, so two runs over the same input produce byte-identical
reports. Nothing here is concurrent: evaluators are independent and pure, and ``asyncio.gather``
would buy nothing while making result order depend on scheduling.

## Synchronous, in-process, not persisted

This slice deliberately builds no background dispatch and no evaluation table. No consumer needs
evaluation history yet, and a persistence layer added "because history will eventually matter"
would be speculative infrastructure of exactly the kind ADR-0017 and ADR-0018 each declined to
build (GP-1: evidence, not anticipation). Reports are returned to the caller. When a real consumer
needs durable history, the tenant-scoped, RLS-forced table it requires can be designed against
that consumer's actual query shape.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from gateway.application.ports.evaluation import (
    EvaluationInput,
    EvaluationOutcome,
    EvaluationResult,
    Evaluator,
)


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Every evaluator's verdict on one inference, in declared order.

    ``results`` is never empty - a report with no verdict would say nothing while looking like a
    clean bill of health, the same failure mode ``RoutingDecision`` prevents by requiring non-empty
    ``reasoning_steps``.

    ``target_failed`` and ``evaluation_degraded`` are separate properties on purpose. Folding them
    into one "unhealthy" flag would make a broken evaluator and a bad response indistinguishable to
    every downstream reader, which is the precise distinction this capability exists to preserve.
    """

    organization_id: UUID
    correlation_id: str
    results: tuple[EvaluationResult, ...]

    def __post_init__(self) -> None:
        if not self.results:
            raise ValueError("an EvaluationReport must carry at least one result")

    @property
    def failures(self) -> tuple[EvaluationResult, ...]:
        return tuple(r for r in self.results if r.outcome is EvaluationOutcome.FAILED)

    @property
    def errors(self) -> tuple[EvaluationResult, ...]:
        return tuple(r for r in self.results if r.outcome is EvaluationOutcome.ERROR)

    @property
    def target_failed(self) -> bool:
        """At least one evaluator judged the inference itself defective."""
        return bool(self.failures)

    @property
    def evaluation_degraded(self) -> bool:
        """At least one evaluator could not produce a verdict. Says nothing about the inference."""
        return bool(self.errors)


class EvaluationRunner:
    """Runs every configured evaluator over one completed inference, in order."""

    def __init__(self, evaluators: Sequence[Evaluator]) -> None:
        if not evaluators:
            # An empty chain would yield an empty report, which the report type forbids for the
            # same reason AgentRuntime refuses an empty agent chain: silence that looks like
            # success. Fail at construction rather than at the first inference.
            raise ValueError("EvaluationRunner requires at least one evaluator")
        self._evaluators = tuple(evaluators)

    @property
    def evaluators(self) -> tuple[Evaluator, ...]:
        return self._evaluators

    async def run(self, target: EvaluationInput) -> EvaluationReport:
        """Evaluate ``target``. Never raises: an evaluator that does is recorded as ``ERROR``."""
        results: list[EvaluationResult] = []
        for evaluator in self._evaluators:
            results.append(await self._verdict(evaluator, target))
        return EvaluationReport(
            organization_id=target.organization_id,
            correlation_id=target.correlation_id,
            results=tuple(results),
        )

    @staticmethod
    async def _verdict(evaluator: Evaluator, target: EvaluationInput) -> EvaluationResult:
        try:
            return await evaluator.evaluate(target)
        except Exception as exc:
            # Deliberately broad: any escaped exception is the evaluator's defect, and letting it
            # propagate would erase every other evaluator's verdict for this inference and
            # (worse) surface a post-hoc observation failure as if the request itself had failed.
            return EvaluationResult(
                evaluator=evaluator.name,
                outcome=EvaluationOutcome.ERROR,
                detail=f"evaluator raised {type(exc).__name__}: {exc}",
            )
