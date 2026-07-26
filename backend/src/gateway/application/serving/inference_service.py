"""InferenceService - the first end-to-end request path (ADR-0016 Slice 15).

Slice 14 gave the stage seam an executor, so admission finally runs. This joins admission to the
execution path that already existed but was reachable only from tests:

    admit (authorization -> policy -> routing)  [Slice 14]
      -> reflect (bounded retry)                [Slice 11]
        -> coordinate (cache -> reserve -> execute -> settle/release)  [Slices 9, 10]
      -> evaluate the final result              [Slice 12]

**It composes; it decides nothing.** Every question already has an owner and keeps it: RBAC answers
whether the principal may act, the policy engine whether the request is admissible, ``AgentRuntime``
which provider, ``ReservationService`` whether the budget allows it, ``ProviderExecutor`` how to
call it, ``CostAccountant`` what it cost, ``RetryPolicy`` whether to try again, and the evaluators
whether the result was sound. This class contributes no judgement of its own - it holds the order,
and the order is the enforcement.

## The property this slice exists to establish

A refused request performs **no downstream work at all**: no routing, no reservation, no provider
call, no settlement, no cache write, no evaluation. Before Slice 14 that could not be asserted,
because nothing executed the stages; before this slice it could not be asserted end to end, because
nothing connected admission to execution. Both halves are now composed in one object, and the
negative tests exercise the composition rather than the parts.

## Why a refusal is not evaluated

Evaluation observes completed inferences. A request that was never admitted produced no inference:
no provider was consulted, no response exists, nothing was spent. Running the evaluator chain over
it would emit ``NOT_APPLICABLE`` verdicts for requests that never entered the system, which would
make every quality metric a function of how much traffic was rejected. ``evaluation`` is therefore
``None`` for a refusal - a distinguishable absence rather than a manufactured verdict.

## Why a refusal synthesizes no ``ProviderResponse``

Returning ``ProviderResponse(ok=False, ...)`` for a denied request would make an admission decision
indistinguishable from a provider failure to every downstream reader, and would invite exactly the
double-counting the evaluators were built to catch. A caller reads ``admitted`` and
``admission.reason``; there is deliberately no shortcut that flattens the two into one field.

## Evaluation runs exactly once, on the final result

Reflection may make several attempts, each reserving and settling under its own attempt-scoped
identity (Slice 11). Evaluation is handed ``reflection.final`` once, after the loop has finished.
Evaluating per attempt would count one logical request several times and would report a transient
failure that a retry already recovered from as a quality problem.

## Phase 5 M1: one admission path, two delivery shapes

``serve_stream`` is the streamed counterpart of ``serve``. It is a second **method**, not a second
service, and that is the point: it runs the *same* ``RequestPipeline`` instance, in the same order,
and reads the routing result back with the same ``_routing_execution``. "Denied at admission means
no reservation, no provider call, no settlement and no cache write" is therefore one property of
one composition rather than the same claim asserted twice about two chains that could drift apart.

Two things the streamed path deliberately does **not** do:

* **It does not reflect.** Retry is the unary path's; a stream cannot be replayed once output has
  escaped, and this service could not tell the difference from outside. ``StreamingCoordinator``'s
  docstring records why the boundary is structural rather than a runtime flag.
* **It does not evaluate.** Evaluation observes a *completed* inference: it needs the outcome, the
  response and the usage together (``ports/evaluation.py``). This method returns while the stream
  is still open, so there is nothing completed to hand an evaluator. Attaching one would require a
  completion callback that nothing owns and nothing asks for - so it is recorded as a limitation
  rather than approximated with a verdict about a response nobody has seen yet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from gateway.application.evaluation.runner import EvaluationReport, EvaluationRunner
from gateway.application.pipeline.runner import AdmissionOutcome, RequestPipeline
from gateway.application.ports.evaluation import EvaluationInput
from gateway.application.ports.pipeline import StageContext
from gateway.application.ports.providers import InferenceRequest
from gateway.application.ports.routing import ROUTING_EXECUTION_KEY, RoutingExecution
from gateway.application.reflection.reflective_executor import ReflectionResult, ReflectiveExecutor
from gateway.application.streaming.streaming_coordinator import StreamingCoordinator, StreamSession
from gateway.observability.metrics import NOT_ADMITTED, record_served_request


class RoutingTransportError(RuntimeError):
    """An admitted request carried no ``RoutingExecution``.

    A defect in the composed chain, not a fact about the request: the pipeline admitted it, so the
    routing stage ran and must have annotated a result. Raising keeps it out of the response path,
    where it would masquerade as a provider or budget failure - the same reasoning
    ``RoutingIntegrityError`` applies inside the engine.
    """


@dataclass(frozen=True, slots=True)
class ServedInference:
    """Everything that happened to one request, with the parts that did not happen absent.

    ``reflection`` and ``evaluation`` are ``None`` exactly when the request was refused. They are
    separate optional fields rather than a synthesized failure result so that "denied at
    admission", "routed nowhere", "denied by budget" and "the provider failed" stay four
    distinguishable facts instead of one ``ok=False``.
    """

    admission: AdmissionOutcome
    reflection: ReflectionResult | None = None
    evaluation: EvaluationReport | None = None

    def __post_init__(self) -> None:
        if self.admission.admitted and self.reflection is None:
            raise ValueError("an admitted request must record an execution result")
        if not self.admission.admitted and self.reflection is not None:
            raise ValueError("a refused request cannot have been executed")

    @property
    def admitted(self) -> bool:
        return self.admission.admitted

    @property
    def refusal_reason(self) -> str | None:
        """The caller-visible reason, or ``None`` when the request was admitted."""
        return self.admission.reason


@dataclass(frozen=True, slots=True)
class ServedStream:
    """The streamed counterpart of ``ServedInference``: an admission verdict plus, if admitted,
    the opened ``StreamSession``.

    ``session`` is ``None`` exactly when the request was refused - the same "absent rather than
    synthesized" discipline ``ServedInference`` applies, and for the same reason: a refusal must
    not be readable as a provider failure or an empty stream.
    """

    admission: AdmissionOutcome
    session: StreamSession | None = None

    def __post_init__(self) -> None:
        if self.admission.admitted and self.session is None:
            raise ValueError("an admitted request must record a stream session")
        if not self.admission.admitted and self.session is not None:
            raise ValueError("a refused request cannot have opened a stream")

    @property
    def admitted(self) -> bool:
        return self.admission.admitted

    @property
    def refusal_reason(self) -> str | None:
        return self.admission.reason


class InferenceService:
    """Serves one inference request: admit, execute if admitted, then evaluate what happened."""

    def __init__(
        self,
        pipeline: RequestPipeline,
        executor: ReflectiveExecutor,
        evaluation_runner: EvaluationRunner,
        streaming_coordinator: StreamingCoordinator,
    ) -> None:
        self._pipeline = pipeline
        self._executor = executor
        self._evaluation_runner = evaluation_runner
        self._streaming_coordinator = streaming_coordinator

    async def serve(self, context: StageContext, request: InferenceRequest) -> ServedInference:
        """Run the admission chain, and only on admission the execution and evaluation path."""
        # Slice 16: this component owns the served request end to end, so it measures it end to
        # end - monotonic, so a wall-clock adjustment mid-request cannot produce a negative or
        # wild duration.
        started = time.monotonic()

        admission = await self._pipeline.admit(context)
        if not admission.admitted:
            # The single most important line in this slice: everything below is unreachable for a
            # refused request, so no reservation, provider call, settlement or cache write can
            # follow a denial.
            record_served_request(outcome=NOT_ADMITTED, duration_seconds=time.monotonic() - started)
            return ServedInference(admission=admission)

        execution = self._routing_execution(admission)
        reflection = await self._executor.execute(execution, request)
        evaluation = await self._evaluation_runner.run(
            EvaluationInput(
                organization_id=execution.decision.organization_id,
                correlation_id=request.correlation_id,
                outcome=reflection.final.outcome,
                response=reflection.final.response,
            )
        )
        record_served_request(
            outcome=reflection.final.outcome.value, duration_seconds=time.monotonic() - started
        )
        return ServedInference(admission=admission, reflection=reflection, evaluation=evaluation)

    async def serve_stream(self, context: StageContext, request: InferenceRequest) -> ServedStream:
        """Run the same admission chain, and only on admission open a provider stream.

        The recorded duration is admission through the **first event**, not the whole stream: this
        method returns while the stream is still open, so a whole-stream duration would need a
        completion callback nothing owns. Time-to-first-byte is the honest thing to measure from
        here, and it is the number this path exists to improve.
        """
        started = time.monotonic()

        admission = await self._pipeline.admit(context)
        if not admission.admitted:
            # Same line, same guarantee as ``serve``: nothing below runs for a refused request.
            record_served_request(outcome=NOT_ADMITTED, duration_seconds=time.monotonic() - started)
            return ServedStream(admission=admission)

        execution = self._routing_execution(admission)
        session = await self._streaming_coordinator.open(execution, request)
        record_served_request(
            outcome=session.outcome.value, duration_seconds=time.monotonic() - started
        )
        return ServedStream(admission=admission, session=session)

    @staticmethod
    def _routing_execution(admission: AdmissionOutcome) -> RoutingExecution:
        """Read the routing result the pipeline transported.

        Searched across the admission records rather than assumed to be last, because ordering is
        the composition root's decision and this class must not encode a copy of it. An unrouted
        execution is returned unchanged: refusing to route is a decision the agents made and
        explained, and it flows on to the coordinator, which already owns that path.
        """
        for record in admission.records:
            candidate = record.annotations.get(ROUTING_EXECUTION_KEY)
            if isinstance(candidate, RoutingExecution):
                return candidate
        raise RoutingTransportError(
            "the request was admitted but no routing execution was transported; "
            f"stages run: {', '.join(admission.stages_run)}"
        )
