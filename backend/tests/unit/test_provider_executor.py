"""ProviderExecutor and ProviderClient tests (ADR-0016 Slice 7).

Fail-safe paths first: the executor's most important behaviour is what it *refuses* to do - call
a provider for a request that was never routed, or override a routing outcome it does not own.

Also the Rule-4 experiment for this port: can ``ProviderClient`` be validated by two independent
implementations with no protocol change? ``InMemoryProviderClient`` (always succeeds) and
``FakeProviderClient`` (scriptable) both exercise ``ProviderExecutor`` unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from gateway.adapters.providers.fake_client import FakeProviderClient
from gateway.adapters.providers.in_memory_client import InMemoryProviderClient
from gateway.application.ports.providers import InferenceRequest, ProviderClient, ProviderResponse
from gateway.application.ports.routing import RoutingExecution
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.domain.routing.models import ReasoningStep, RoutingDecision, RoutingOutcome

ORG = uuid4()
OPENAI = ProviderDescriptor(name="openai", model="gpt-4o")


def _decision(outcome: RoutingOutcome, selected_provider: str | None = None) -> RoutingDecision:
    return RoutingDecision(
        outcome=outcome,
        organization_id=ORG,
        correlation_id="corr-1",
        decided_at=datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC),
        reasoning_steps=(ReasoningStep(agent="provider", summary="stub"),),
        selected_provider=selected_provider,
    )


def _request(**payload: object) -> InferenceRequest:
    return InferenceRequest(correlation_id="corr-1", payload=payload)


# ------------------------------------------------------------------ fail-safe paths first


async def test_unrouted_execution_is_never_sent_to_the_client() -> None:
    """A denial must not be overridden into a provider call the executor does not own."""
    client = FakeProviderClient()
    executor = ProviderExecutor(client)
    execution = RoutingExecution(decision=_decision(RoutingOutcome.NO_CANDIDATE))

    response = await executor.execute(execution, _request(prompt="hi"))

    assert response.ok is False
    assert response.error == "not_routed: no_candidate"
    assert client.calls == []


async def test_policy_denial_is_never_sent_to_the_client() -> None:
    client = FakeProviderClient()
    executor = ProviderExecutor(client)
    execution = RoutingExecution(decision=_decision(RoutingOutcome.BLOCKED_BY_POLICY))

    response = await executor.execute(execution, _request())

    assert response.ok is False
    assert response.error == "not_routed: blocked_by_policy"
    assert client.calls == []


async def test_provider_failure_is_data_not_an_exception() -> None:
    client = FakeProviderClient(unreachable=True)
    executor = ProviderExecutor(client)
    execution = RoutingExecution(
        decision=_decision(RoutingOutcome.SELECTED, "openai"), provider=OPENAI
    )

    response = await executor.execute(execution, _request(prompt="hi"))

    assert response.ok is False
    assert response.error == "simulated provider unreachable"


# ------------------------------------------------------------------ success


async def test_routed_execution_invokes_the_resolved_provider() -> None:
    scripted = ProviderResponse(ok=True, content={"text": "hello"}, provider="openai")
    client = FakeProviderClient(responses={"openai": scripted})
    executor = ProviderExecutor(client)
    execution = RoutingExecution(
        decision=_decision(RoutingOutcome.SELECTED, "openai"), provider=OPENAI
    )
    request = _request(prompt="hi")

    response = await executor.execute(execution, request)

    assert response is scripted
    assert client.calls == [(OPENAI, request)]


async def test_in_memory_client_always_succeeds_and_echoes_the_payload() -> None:
    executor = ProviderExecutor(InMemoryProviderClient())
    execution = RoutingExecution(
        decision=_decision(RoutingOutcome.SELECTED, "openai"), provider=OPENAI
    )

    response = await executor.execute(execution, _request(prompt="hi"))

    assert response.ok is True
    assert response.provider == "openai"
    assert response.content == {"provider": "openai", "model": "gpt-4o", "echo": {"prompt": "hi"}}


# ------------------------------------------------------------------ Rule 4: both clients satisfy


def test_both_provider_clients_satisfy_the_protocol() -> None:
    assert isinstance(InMemoryProviderClient(), ProviderClient)
    assert isinstance(FakeProviderClient(), ProviderClient)


async def test_a_missing_script_fails_closed_rather_than_guessing() -> None:
    """Rule 4 discovery: an unscripted provider must deny, never default to success."""
    client = FakeProviderClient()
    response = await client.invoke(OPENAI, _request())
    assert response.ok is False
    assert "no scripted response" in (response.error or "")
