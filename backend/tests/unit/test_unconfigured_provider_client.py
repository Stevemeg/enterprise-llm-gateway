"""UnconfiguredProviderClient tests (Phase 5 M2).

One property, asserted from several directions: **a deployment that cannot reach a provider must
never produce a successful inference.** Before M2 the fallback was ``InMemoryProviderClient``,
whose contract is "always succeeds" and which synthesizes ``ProviderUsage`` - so a misconfigured
production gateway answered 200 with invented content and booked real spend for it.
"""

from __future__ import annotations

from uuid import uuid4

from gateway.adapters.providers.unconfigured_client import UnconfiguredProviderClient
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderClient,
    ProviderErrorCategory,
)
from gateway.application.ports.streaming import StreamFailed, StreamingProviderClient
from gateway.application.routing.catalog import ProviderDescriptor

PROVIDER = ProviderDescriptor(name="openai", model="gpt-4o")
REQUEST = InferenceRequest(correlation_id=str(uuid4()), payload={"prompt": "hello"})


def test_it_satisfies_both_provider_ports() -> None:
    """It has to be a drop-in for whichever client the composition root would otherwise wire, in
    both delivery shapes - a fallback that only covered one would leave the other fabricating."""
    client = UnconfiguredProviderClient()
    assert isinstance(client, ProviderClient)
    assert isinstance(client, StreamingProviderClient)


async def test_a_unary_call_never_succeeds_and_reports_no_usage() -> None:
    """``usage=None`` matters as much as ``ok=False``: usage is what settlement turns into money,
    so a fallback that reported any would let a fabricated call be charged for."""
    response = await UnconfiguredProviderClient().invoke(PROVIDER, REQUEST)

    assert response.ok is False
    assert response.usage is None
    assert response.content is None
    assert response.error_category is ProviderErrorCategory.AUTHENTICATION


async def test_a_unary_failure_is_not_retryable() -> None:
    """AUTHENTICATION is outside the transient set, so reflection terminates instead of spending
    the whole attempt budget on a misconfiguration that cannot resolve itself."""
    from gateway.application.ports.providers import TRANSIENT_PROVIDER_ERROR_CATEGORIES

    response = await UnconfiguredProviderClient().invoke(PROVIDER, REQUEST)

    assert response.error_category not in TRANSIENT_PROVIDER_ERROR_CATEGORIES


async def test_a_stream_yields_exactly_one_terminal_failure_and_no_content() -> None:
    events = [event async for event in UnconfiguredProviderClient().stream(PROVIDER, REQUEST)]

    assert len(events) == 1
    failure = events[0]
    assert isinstance(failure, StreamFailed)
    assert failure.error_category is ProviderErrorCategory.AUTHENTICATION


async def test_it_names_no_configuration_key_in_anything_a_caller_can_see() -> None:
    """The operator gets the remedy from the log line; the caller must not learn which
    environment variables this deployment is missing."""
    response = await UnconfiguredProviderClient().invoke(PROVIDER, REQUEST)
    events = [event async for event in UnconfiguredProviderClient().stream(PROVIDER, REQUEST)]

    visible = f"{response.error} {events[0]}"
    assert "GATEWAY_" not in visible
    assert "BASE_URL" not in visible
