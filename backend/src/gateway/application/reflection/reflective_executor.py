"""ReflectiveExecutor - bounded, explainable retry around one already-routed request
(ADR-0016 Slice 11).

Owns exactly one responsibility: **whether another attempt is warranted, and how many times**.
Everything else is delegated to the component that already owns it, unchanged:

* routing            - ``AgentRuntime``/``RoutingEngine`` (the ``RoutingExecution`` arrives decided)
* caching / dedup    - ``InferenceCoordinator`` (Slice 10)
* budget gating      - ``ReservationService`` (Slice 9), reached only via the coordinator
* provider execution - ``ProviderExecutor`` (Slice 7), reached only via the coordinator
* actual cost        - ``CostAccountant`` (Slice 8), reached only via the coordinator

Its only collaborator is ``InferenceCoordinator``. That is deliberate and is what makes "retries
cannot bypass ProviderExecutor / budget enforcement / the cache" structural rather than reviewed:
this package cannot import ``application.providers``, ``application.accounting``,
``application.routing`` or ``ports.ledger`` at all (import-linter, Slice 11), so there is no path
by which a retry could reach a provider without also passing the budget gate.

## No rerouting, and why that is a decision rather than an omission

Reflection retries the **same** ``RoutingExecution`` it was given. It never selects a different
provider, because provider selection is ``ProviderAgent``'s job inside ``AgentRuntime``, and the
routing architecture does not delegate that decision here. Rerouting would mean either fabricating
a second provider choice outside the only component allowed to explain one, or invoking routing
again to produce a *second* ``RoutingDecision`` for one logical request - two explanations of the
same request, which is exactly the failure ``RoutingExecution``'s own design note warns about.
Neither has a consumer in this milestone, so neither is built (Rule 5). ``ReflectionResult`` carries
the original decision unmodified; nothing here mutates it (it is frozen regardless).

## Attempt identity: why each attempt gets its own correlation id

Budget reservation and settlement are keyed on ``(organization_id, correlation_id)`` (Slice 9). If
every attempt reused the caller's bare ``correlation_id``, attempt 2's ``reserve`` would collide
with attempt 1's finished reservation and attempt 2's ``settle`` would be swallowed as a duplicate -
the tenant would receive a second provider call it was never charged for. Each attempt therefore
executes under a derived id, ``"<correlation_id>#<attempt>"``, so every attempt reserves, settles
or releases independently and is independently auditable in ``cost_ledger``.

This derivation is safe against both Slice-10 identities by construction:

* **Cache identity** ignores ``correlation_id`` entirely (it is content-keyed), so retrying does
  not change which cache entry an attempt reads or writes - a retry can still be served by a
  response an earlier request cached.
* **Deduplication identity** is ``(organization_id, correlation_id)``, so two concurrent duplicate
  requests derive the *same* attempt id at each step and coalesce at every attempt. N duplicate
  callers therefore produce one provider call per attempt, not N - the retry storm this could
  otherwise become is prevented by the Slice-10 mechanism, unchanged.

The derived id is recorded on every ``AttemptRecord``, so the trace never leaves a reader guessing
which ledger row belongs to which attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from gateway.application.execution.inference_coordinator import (
    ExecutionOutcome,
    InferenceCoordinator,
    InferenceExecutionResult,
)
from gateway.application.ports.providers import InferenceRequest, ProviderErrorCategory
from gateway.application.ports.routing import RoutingExecution
from gateway.application.reflection.retry_policy import RetryPolicy, RetryVerdict, classify
from gateway.shared.clock import Sleeper


def attempt_correlation_id(correlation_id: str, attempt: int) -> str:
    """The identity one attempt executes under. Deterministic and inspectable, never random."""
    return f"{correlation_id}#{attempt}"


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """What happened on one attempt. The reflection trace's unit, analogous to ``ReasoningStep``
    for routing - and, like it, deliberately *not* folded into ``RoutingDecision``: routing
    explains which provider was chosen, this explains how many times it was called."""

    attempt: int
    correlation_id: str
    outcome: ExecutionOutcome
    verdict: RetryVerdict
    error: str | None = None
    error_category: ProviderErrorCategory | None = None


@dataclass(frozen=True, slots=True)
class ReflectionResult:
    """The complete outcome of a reflected execution.

    ``attempts`` is never empty - a result with no recorded attempt would be unexplainable, the
    same property ``RoutingDecision.reasoning_steps`` guarantees for routing. ``final`` is the
    last attempt's result verbatim, so a caller that does not care about retries can read it
    exactly as it would read a plain ``InferenceCoordinator`` result.
    """

    final: InferenceExecutionResult
    attempts: tuple[AttemptRecord, ...]
    execution: RoutingExecution

    def __post_init__(self) -> None:
        if not self.attempts:
            raise ValueError("a ReflectionResult must record at least one attempt")

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    @property
    def retried(self) -> bool:
        return len(self.attempts) > 1

    @property
    def succeeded(self) -> bool:
        return self.attempts[-1].verdict is RetryVerdict.SUCCEEDED

    @property
    def exhausted(self) -> bool:
        """True when the loop stopped because it ran out of attempts, not because it was done."""
        return self.attempts[-1].verdict is RetryVerdict.RETRY


class ReflectiveExecutor:
    """Runs an already-routed request through the coordinator, retrying only transient failures."""

    def __init__(
        self, coordinator: InferenceCoordinator, policy: RetryPolicy, sleeper: Sleeper
    ) -> None:
        self._coordinator = coordinator
        self._policy = policy
        self._sleeper = sleeper

    async def execute(
        self, execution: RoutingExecution, request: InferenceRequest
    ) -> ReflectionResult:
        """Attempt the request up to ``policy.max_attempts`` times. Terminates on the first
        success or terminal failure; never loops unbounded (the range is finite by construction)."""
        attempts: list[AttemptRecord] = []
        result: InferenceExecutionResult | None = None

        for attempt in range(1, self._policy.max_attempts + 1):
            if attempt > 1:
                await self._sleeper.sleep(self._policy.backoff_before(attempt))

            attempt_request = replace(
                request, correlation_id=attempt_correlation_id(request.correlation_id, attempt)
            )
            result = await self._coordinator.execute(execution, attempt_request)
            verdict = classify(result)
            attempts.append(
                AttemptRecord(
                    attempt=attempt,
                    correlation_id=attempt_request.correlation_id,
                    outcome=result.outcome,
                    verdict=verdict,
                    error=result.response.error,
                    error_category=result.response.error_category,
                )
            )
            if verdict is not RetryVerdict.RETRY:
                break

        if result is None:  # pragma: no cover - max_attempts >= 1, so the loop always ran once
            raise AssertionError("RetryPolicy guarantees at least one attempt")
        return ReflectionResult(final=result, attempts=tuple(attempts), execution=execution)
