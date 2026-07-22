"""Pre-call usage estimation tests (ADR-0016 Slice 9)."""

from __future__ import annotations

from gateway.application.accounting.estimator import estimate_usage
from gateway.application.ports.providers import InferenceRequest


def test_empty_payload_still_estimates_at_least_one_token_of_each_kind() -> None:
    estimate = estimate_usage(InferenceRequest(correlation_id="c1", payload={}))

    assert estimate.prompt_tokens >= 1
    assert estimate.completion_tokens >= 1


def test_estimate_is_deterministic_for_the_same_payload() -> None:
    request = InferenceRequest(correlation_id="c1", payload={"prompt": "hello world" * 10})

    first = estimate_usage(request)
    second = estimate_usage(request)

    assert first == second


def test_larger_payload_estimates_more_tokens() -> None:
    small = estimate_usage(InferenceRequest(correlation_id="c1", payload={"prompt": "hi"}))
    large = estimate_usage(
        InferenceRequest(correlation_id="c2", payload={"prompt": "hello world " * 200})
    )

    assert large.prompt_tokens > small.prompt_tokens


def test_estimate_conservatively_assumes_completion_as_large_as_prompt() -> None:
    """Deliberately more conservative than InMemoryProviderClient's own actual-usage synthesis
    (which assumes completion is half the prompt) - a reservation should not under-reserve."""
    estimate = estimate_usage(
        InferenceRequest(correlation_id="c1", payload={"prompt": "hello world " * 50})
    )

    assert estimate.completion_tokens == estimate.prompt_tokens
