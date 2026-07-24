"""Deterministic evaluator tests (ADR-0016 Slice 12).

Both evaluators are pure functions of a completed outcome, so every case is exercised directly
against constructed inputs - no provider, no database, no clock, no randomness.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.ports.evaluation import (
    EvaluationInput,
    EvaluationOutcome,
    EvaluationResult,
    Evaluator,
)
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.providers import ProviderResponse, ProviderUsage

ORG = uuid4()
USAGE = ProviderUsage(prompt_tokens=10, completion_tokens=5)


def _input(
    outcome: ExecutionOutcome,
    *,
    ok: bool = True,
    content: object = None,
    usage: ProviderUsage | None = None,
) -> EvaluationInput:
    return EvaluationInput(
        organization_id=ORG,
        correlation_id="c1",
        outcome=outcome,
        response=ProviderResponse(
            ok=ok,
            content=content,
            error=None if ok else "boom",
            provider="openai",
            usage=usage,
        ),
    )


# ------------------------------------------------------------------ response completeness


async def test_successful_response_with_content_passes() -> None:
    result = await ResponseCompletenessEvaluator().evaluate(
        _input(ExecutionOutcome.EXECUTED, content={"text": "hi"}, usage=USAGE)
    )

    assert result.outcome is EvaluationOutcome.PASSED
    assert result.evaluator == "response_completeness"


async def test_successful_response_without_content_fails() -> None:
    """The real defect class: ProviderResponse.content is Any with a None default, so an adapter
    can report success while delivering nothing - and Slice 10 would cache it."""
    result = await ResponseCompletenessEvaluator().evaluate(
        _input(ExecutionOutcome.EXECUTED, content=None, usage=USAGE)
    )

    assert result.outcome is EvaluationOutcome.FAILED
    assert "no content" in result.detail


async def test_cache_hit_with_content_passes() -> None:
    result = await ResponseCompletenessEvaluator().evaluate(
        _input(ExecutionOutcome.CACHE_HIT, content={"text": "cached"}, usage=None)
    )

    assert result.outcome is EvaluationOutcome.PASSED


@pytest.mark.parametrize(
    "outcome",
    [
        ExecutionOutcome.NOT_ROUTED,
        ExecutionOutcome.BUDGET_DENIED,
        ExecutionOutcome.BUDGET_UNAVAILABLE,
    ],
)
async def test_non_delivering_outcomes_are_not_applicable(outcome: ExecutionOutcome) -> None:
    """A denial is already explained by ExecutionOutcome; restating it as FAILED would
    double-count one incident in any metric built on both."""
    result = await ResponseCompletenessEvaluator().evaluate(_input(outcome, ok=False))

    assert result.outcome is EvaluationOutcome.NOT_APPLICABLE


async def test_a_failed_provider_call_is_not_applicable_not_failed() -> None:
    result = await ResponseCompletenessEvaluator().evaluate(
        _input(ExecutionOutcome.EXECUTED, ok=False)
    )

    assert result.outcome is EvaluationOutcome.NOT_APPLICABLE


# ------------------------------------------------------------------ usage consistency


async def test_executed_success_with_usage_passes() -> None:
    result = await UsageAccountingConsistencyEvaluator().evaluate(
        _input(ExecutionOutcome.EXECUTED, content={"t": 1}, usage=USAGE)
    )

    assert result.outcome is EvaluationOutcome.PASSED


async def test_executed_success_without_usage_fails() -> None:
    """Without usage, CostAccountant raises MissingUsageError and the reservation cannot settle -
    so this is either unbooked spend or a still-held budget reservation."""
    result = await UsageAccountingConsistencyEvaluator().evaluate(
        _input(ExecutionOutcome.EXECUTED, content={"t": 1}, usage=None)
    )

    assert result.outcome is EvaluationOutcome.FAILED
    assert "cannot be settled" in result.detail


async def test_cache_hit_without_usage_passes() -> None:
    """Slice 10 sets usage=None on a hit deliberately: no provider was called."""
    result = await UsageAccountingConsistencyEvaluator().evaluate(
        _input(ExecutionOutcome.CACHE_HIT, content={"t": 1}, usage=None)
    )

    assert result.outcome is EvaluationOutcome.PASSED


async def test_cache_hit_reporting_usage_fails() -> None:
    """The opposite direction: usage on a hit means the cache invented consumption, and anything
    metering it would over-bill."""
    result = await UsageAccountingConsistencyEvaluator().evaluate(
        _input(ExecutionOutcome.CACHE_HIT, content={"t": 1}, usage=USAGE)
    )

    assert result.outcome is EvaluationOutcome.FAILED
    assert "no provider was called" in result.detail


@pytest.mark.parametrize("outcome", [ExecutionOutcome.NOT_ROUTED, ExecutionOutcome.BUDGET_DENIED])
async def test_non_billable_outcomes_are_not_applicable(outcome: ExecutionOutcome) -> None:
    result = await UsageAccountingConsistencyEvaluator().evaluate(_input(outcome, ok=False))

    assert result.outcome is EvaluationOutcome.NOT_APPLICABLE


# ------------------------------------------------------------------ port conformance / typing


def test_both_evaluators_satisfy_the_protocol() -> None:
    assert isinstance(ResponseCompletenessEvaluator(), Evaluator)
    assert isinstance(UsageAccountingConsistencyEvaluator(), Evaluator)


def test_evaluator_names_are_distinct_and_overridable() -> None:
    assert ResponseCompletenessEvaluator().name != UsageAccountingConsistencyEvaluator().name
    assert ResponseCompletenessEvaluator(name="custom").name == "custom"


@pytest.mark.parametrize("outcome", [EvaluationOutcome.FAILED, EvaluationOutcome.ERROR])
def test_a_failed_or_errored_result_must_explain_itself(outcome: EvaluationOutcome) -> None:
    """Mirrors StageResult requiring a reason for BLOCK: an unexplained negative verdict is not
    actionable."""
    with pytest.raises(ValueError, match="must carry a detail"):
        EvaluationResult(evaluator="x", outcome=outcome, detail="")


def test_a_result_must_name_its_evaluator() -> None:
    with pytest.raises(ValueError, match="must identify the evaluator"):
        EvaluationResult(evaluator="", outcome=EvaluationOutcome.PASSED)
