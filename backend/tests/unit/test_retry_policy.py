"""RetryPolicy and retry classification tests (ADR-0016 Slice 11).

Fail-safe paths first: what reflection *refuses* to retry matters more than what it retries -
retrying a permanent failure charges the tenant again for a call that cannot succeed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from gateway.application.execution.inference_coordinator import (
    ExecutionOutcome,
    InferenceExecutionResult,
)
from gateway.application.ports.providers import ProviderErrorCategory, ProviderResponse
from gateway.application.reflection.retry_policy import RetryPolicy, RetryVerdict, classify


def _result(
    outcome: ExecutionOutcome,
    *,
    ok: bool = False,
    category: ProviderErrorCategory | None = None,
) -> InferenceExecutionResult:
    return InferenceExecutionResult(
        outcome=outcome,
        response=ProviderResponse(ok=ok, error=None if ok else "boom", error_category=category),
    )


# ------------------------------------------------------------------ never retried


def test_policy_or_no_candidate_denial_is_never_retried() -> None:
    """NOT_ROUTED covers policy denial, no-candidate and all-unhealthy - decisions already made
    and already explained by RoutingDecision, not transient faults."""
    assert classify(_result(ExecutionOutcome.NOT_ROUTED)) is RetryVerdict.TERMINAL_FAILURE


def test_budget_denial_is_never_retried() -> None:
    assert classify(_result(ExecutionOutcome.BUDGET_DENIED)) is RetryVerdict.TERMINAL_FAILURE


def test_budget_store_outage_is_never_retried() -> None:
    """Already a fail-closed denial; retrying would aim more load at a struggling ledger."""
    assert classify(_result(ExecutionOutcome.BUDGET_UNAVAILABLE)) is RetryVerdict.TERMINAL_FAILURE


@pytest.mark.parametrize(
    "category", [ProviderErrorCategory.INVALID_REQUEST, ProviderErrorCategory.AUTHENTICATION]
)
def test_permanent_provider_errors_are_never_retried(category: ProviderErrorCategory) -> None:
    result = _result(ExecutionOutcome.EXECUTED, category=category)
    assert classify(result) is RetryVerdict.TERMINAL_FAILURE


def test_an_unclassified_provider_failure_is_not_retried() -> None:
    """Fail closed: an error nobody classified is not known to be transient."""
    result = _result(ExecutionOutcome.EXECUTED, category=None)
    assert classify(result) is RetryVerdict.TERMINAL_FAILURE


# ------------------------------------------------------------------ retried


@pytest.mark.parametrize(
    "category",
    [
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.SERVER_ERROR,
    ],
)
def test_transient_provider_errors_are_retried(category: ProviderErrorCategory) -> None:
    result = _result(ExecutionOutcome.EXECUTED, category=category)
    assert classify(result) is RetryVerdict.RETRY


# ------------------------------------------------------------------ success


def test_a_successful_execution_succeeds() -> None:
    assert classify(_result(ExecutionOutcome.EXECUTED, ok=True)) is RetryVerdict.SUCCEEDED


def test_a_cache_hit_succeeds_immediately() -> None:
    assert classify(_result(ExecutionOutcome.CACHE_HIT, ok=True)) is RetryVerdict.SUCCEEDED


# ------------------------------------------------------------------ policy bounds


def test_default_policy_is_bounded_and_conservative() -> None:
    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.base_backoff > timedelta(0)


def test_max_attempts_below_one_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        RetryPolicy(max_attempts=0)


def test_negative_backoff_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="not be negative"):
        RetryPolicy(base_backoff=timedelta(seconds=-1))


def test_max_attempts_of_one_is_valid_and_means_no_retry() -> None:
    assert RetryPolicy(max_attempts=1).max_attempts == 1


def test_backoff_grows_exponentially_without_jitter() -> None:
    """Deterministic by design - no random jitter, so the delay sequence is inspectable."""
    policy = RetryPolicy(base_backoff=timedelta(milliseconds=100))

    assert policy.backoff_before(2) == timedelta(milliseconds=100)
    assert policy.backoff_before(3) == timedelta(milliseconds=200)
    assert policy.backoff_before(4) == timedelta(milliseconds=400)
