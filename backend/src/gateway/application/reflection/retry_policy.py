"""Retry classification and bounds (ADR-0016 Slice 11).

Two facts, both typed rather than scattered as magic numbers and ad-hoc conditionals (Rule 3):

* ``RetryPolicy`` - how many attempts are permitted and how long to wait between them.
* ``classify()`` - whether a completed attempt warrants another one.

Classification is **fail-closed**: an outcome is retryable only if it is positively known to be
transient. Anything unrecognised, unclassified, or denied is terminal. Retrying a permanent failure
costs the tenant a second (and third) provider charge for a call that cannot succeed, so the
default direction of the error matters more here than in most classification code.

## What never retries, and why

* **Policy denial, authorization denial, no-candidate, all-unhealthy** - all arrive as
  ``NOT_ROUTED``. These are *decisions*, already made and already explained by ``RoutingDecision``.
  A retry would be this layer asking a question that was already answered, hoping for a different
  reply. (Authorization specifically is decided upstream in the pipeline and never reaches this
  layer at all - see ``reflective_executor.py``.)
* **Budget denial** - the tenant is out of money. A second attempt spends nothing new because
  reservation gates it, but it is still a guaranteed-identical answer.
* **Budget store unavailable** - already a fail-closed denial (ADR-0009 row 1). Retrying would
  aim repeated load at a ledger that is already struggling, which is how a partial outage becomes
  a total one.
* **An unclassified provider failure** (``error_category is None``) - not known to be transient.

## What retries

Exactly the three provider failure categories that are transient by definition: ``TIMEOUT``,
``RATE_LIMITED``, ``SERVER_ERROR``. ``INVALID_REQUEST`` and ``AUTHENTICATION`` are permanent
until a human changes something, so they terminate.

**Malformed provider output** deliberately has no category here: usage that is missing or negative
surfaces as ``MissingUsageError``/``MalformedUsageError`` raised by ``CostAccountant`` during
settlement, which that module documents as a *defect a human must fix*, never a business outcome.
Reflection does not catch exceptions as retry signals - retrying a defect is precisely wrong, and
converting one into a silent retry would erase the signal that something needs fixing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from gateway.application.execution.inference_coordinator import (
    InferenceExecutionResult,
)
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.providers import ProviderErrorCategory

_RETRYABLE_PROVIDER_ERRORS = frozenset(
    {
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.SERVER_ERROR,
    }
)


class RetryVerdict(StrEnum):
    """What a completed attempt means for the reflection loop (closed vocabulary, safe as a
    metric label - mirrors ``RoutingOutcome``/``ExecutionOutcome``)."""

    SUCCEEDED = "succeeded"
    RETRY = "retry"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How many attempts are permitted, and the backoff between them.

    A typed object rather than two loose parameters because both are domain limits a future
    caller will want to configure per tenant or per route, and an untyped pair would let a caller
    silently swap them. ``max_attempts`` counts *total* attempts, not retries: ``1`` means
    "never retry", which is why it is the floor rather than ``0``.
    """

    max_attempts: int = 3
    base_backoff: timedelta = timedelta(milliseconds=100)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(
                f"max_attempts must be at least 1 (1 = no retry), got {self.max_attempts}"
            )
        if self.base_backoff < timedelta(0):
            raise ValueError(f"base_backoff must not be negative, got {self.base_backoff}")

    def backoff_before(self, next_attempt: int) -> timedelta:
        """Delay before ``next_attempt`` (2nd attempt waits ``base``, 3rd ``2x base``, ...).

        Exponential because the dominant retryable case is rate limiting, where retrying at a
        fixed interval reproduces the condition that caused the limit. No random jitter: jitter
        exists to de-synchronise a fleet of callers, and this project has no such fleet and no
        requirement describing one (Rule 5 - it would be an untestable knob with no consumer).
        """
        multiplier: int = 2 ** (next_attempt - 2)
        return timedelta(seconds=self.base_backoff.total_seconds() * multiplier)


def classify(result: InferenceExecutionResult) -> RetryVerdict:
    """Decide what one completed attempt means. Never raises; never inspects a provider directly."""
    if result.outcome is ExecutionOutcome.CACHE_HIT:
        # A cached response is a complete, correct answer - reflection stops immediately, and
        # no attempt after the first can ever be needed.
        return RetryVerdict.SUCCEEDED
    if result.outcome is ExecutionOutcome.EXECUTED and result.response.ok:
        return RetryVerdict.SUCCEEDED
    if result.outcome is not ExecutionOutcome.EXECUTED:
        # NOT_ROUTED / BUDGET_DENIED / BUDGET_UNAVAILABLE - decisions, not transient faults.
        return RetryVerdict.TERMINAL_FAILURE
    if result.response.error_category in _RETRYABLE_PROVIDER_ERRORS:
        return RetryVerdict.RETRY
    return RetryVerdict.TERMINAL_FAILURE
