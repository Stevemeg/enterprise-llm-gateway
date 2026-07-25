"""Contract tests for the OpenAI-compatible provider adapter (ADR-0003, Slice 19).

Real ``httpx`` request/response handling - status codes, headers, JSON decode, timeouts - against
a scripted transport. No network, no provider credits (ADR-0003's "contract tests replaying
recorded provider fixtures to detect drift"). ``httpx.MockTransport`` is a genuine transport, so
everything between ``client.post`` and the transport boundary is the real library.

Failure-first: every way a provider call can go wrong is asserted to become a classified,
text-safe ``ProviderResponse`` before the success path is asserted at all - because "never raise,
never leak" is the adapter's whole contract.
"""

from __future__ import annotations

import httpx
import pytest

from gateway.adapters.providers.openai_compatible_client import (
    OpenAiCompatibleProviderClient,
    ProviderConnection,
)
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
)
from gateway.application.routing.catalog import ProviderDescriptor

PROVIDER = ProviderDescriptor(name="openai", model="gpt-4o", region="global")
CONNECTION = ProviderConnection(
    base_url="https://api.example.test/v1", api_key="sk-secret-value", timeout_seconds=5.0
)
REQUEST = InferenceRequest(correlation_id="c-1", payload={"prompt": "hello"})

_OK_BODY = {
    "choices": [{"message": {"role": "assistant", "content": "hi there"}}],
    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
}


def client_returning(
    handler: object, *, connections: dict[str, ProviderConnection] | None = None
) -> OpenAiCompatibleProviderClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return OpenAiCompatibleProviderClient(
        connections if connections is not None else {"openai": CONNECTION}, transport=transport
    )


async def invoke(
    handler: object, *, connections: dict[str, ProviderConnection] | None = None
) -> ProviderResponse:
    return await client_returning(handler, connections=connections).invoke(PROVIDER, REQUEST)


# ------------------------------------------------------------------ never raises, never leaks


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, ProviderErrorCategory.INVALID_REQUEST),
        (401, ProviderErrorCategory.AUTHENTICATION),
        (403, ProviderErrorCategory.AUTHENTICATION),
        (404, ProviderErrorCategory.INVALID_REQUEST),
        (408, ProviderErrorCategory.TIMEOUT),
        (422, ProviderErrorCategory.INVALID_REQUEST),
        (429, ProviderErrorCategory.RATE_LIMITED),
        (500, ProviderErrorCategory.SERVER_ERROR),
        (502, ProviderErrorCategory.SERVER_ERROR),
        (503, ProviderErrorCategory.SERVER_ERROR),
    ],
)
async def test_http_error_status_maps_to_the_canonical_category(
    status: int, category: ProviderErrorCategory
) -> None:
    """ADR-0003's normalized error taxonomy: failover and retry both key on the category, so the
    HTTP status must never leak upward as its own thing."""
    response = await invoke(
        lambda _req: httpx.Response(status, json={"error": {"message": "UPSTREAM DETAIL"}})
    )
    assert response.ok is False
    assert response.error_category is category


async def test_a_provider_error_body_is_never_echoed() -> None:
    """The provider's own error text is unbounded, provider-authored, and may quote the request.
    The only text on a failure is one of this adapter's own constant strings."""
    response = await invoke(
        lambda _req: httpx.Response(500, json={"error": {"message": "SENSITIVE UPSTREAM DETAIL"}})
    )
    assert "SENSITIVE UPSTREAM DETAIL" not in str(response.error)
    assert "500" in str(response.error)  # the status number is fine; the body is not


async def test_a_timeout_becomes_a_retryable_timeout_category() -> None:
    def _timeout(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=_req)

    response = await invoke(_timeout)
    assert response.ok is False
    assert response.error_category is ProviderErrorCategory.TIMEOUT


async def test_a_transport_error_becomes_a_server_error_and_hides_the_url() -> None:
    def _boom(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed connecting to https://api.example.test/v1", request=_req)

    response = await invoke(_boom)
    assert response.ok is False
    assert response.error_category is ProviderErrorCategory.SERVER_ERROR
    assert "example.test" not in str(response.error)


async def test_a_malformed_success_body_is_a_server_error_not_a_crash() -> None:
    response = await invoke(lambda _req: httpx.Response(200, content=b"this is not json"))
    assert response.ok is False
    assert response.error_category is ProviderErrorCategory.SERVER_ERROR


async def test_valid_json_that_is_not_an_object_is_a_server_error() -> None:
    """A 200 whose body is a JSON array or scalar is still malformed for our purposes - the
    ``json()`` call succeeds, so this exercises the shape check rather than the decode failure."""
    response = await invoke(lambda _req: httpx.Response(200, json=["not", "an", "object"]))
    assert response.ok is False
    assert response.error_category is ProviderErrorCategory.SERVER_ERROR


async def test_an_unnamed_4xx_status_falls_back_to_invalid_request() -> None:
    """A status not in the explicit table and below 500 (e.g. 418) is a client-side rejection -
    INVALID_REQUEST, which is terminal, not retryable."""
    response = await invoke(lambda _req: httpx.Response(418, json={"error": "teapot"}))
    assert response.ok is False
    assert response.error_category is ProviderErrorCategory.INVALID_REQUEST


async def test_an_unconfigured_provider_fails_closed_without_a_call() -> None:
    """A descriptor naming a provider this deployment cannot reach is configuration, not a fault.
    AUTHENTICATION is chosen deliberately because it is NOT retryable - burning the attempt budget
    on a misconfiguration helps no one."""

    def _must_not_run(_req: httpx.Request) -> httpx.Response:  # pragma: no cover - asserted unused
        raise AssertionError("no HTTP call may be made for an unconfigured provider")

    response = await invoke(_must_not_run, connections={})
    assert response.ok is False
    assert response.error_category is ProviderErrorCategory.AUTHENTICATION


# ------------------------------------------------------------------ the request it builds


async def test_the_request_carries_the_model_and_credential_and_prompt() -> None:
    """The model comes from the descriptor, not the payload, so a caller cannot route past the
    agents' selection by smuggling a different model in the body."""
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        captured["auth"] = request.headers.get("Authorization")
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_OK_BODY)

    await client_returning(_capture).invoke(
        PROVIDER, InferenceRequest(correlation_id="c-2", payload={"prompt": "translate this"})
    )

    assert captured["auth"] == "Bearer sk-secret-value"
    assert str(captured["url"]).endswith("/chat/completions")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o"
    assert body["messages"] == [{"role": "user", "content": "translate this"}]


async def test_an_inbound_model_field_cannot_override_the_selected_model() -> None:
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_OK_BODY)

    await client_returning(_capture).invoke(
        PROVIDER,
        InferenceRequest(correlation_id="c-3", payload={"prompt": "hi", "model": "gpt-4o-mini"}),
    )
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-4o", "the descriptor's model must win over an inbound field"


# ------------------------------------------------------------------ the success it returns


async def test_a_successful_call_returns_content_and_usage() -> None:
    response = await invoke(lambda _req: httpx.Response(200, json=_OK_BODY))
    assert response.ok is True
    assert response.provider == "openai"
    assert response.content == "hi there"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 7


async def test_a_success_without_usage_reports_none_not_zero() -> None:
    """Zero and "not reported" are different facts. CostAccountant turns None into MissingUsageError
    at settlement; a fabricated zero would launder a provider defect into a billable number."""
    response = await invoke(
        lambda _req: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )
    assert response.ok is True
    assert response.usage is None


async def test_a_partial_usage_block_is_treated_as_absent() -> None:
    response = await invoke(
        lambda _req: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 5}},
        )
    )
    assert response.ok is True
    assert response.usage is None


async def test_an_unfamiliar_success_shape_falls_back_to_the_whole_body() -> None:
    """Self-hosted servers (FR-024) are not always spec-perfect; a usable 200 should stay usable."""
    body = {"output": "hello", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
    response = await invoke(lambda _req: httpx.Response(200, json=body))
    assert response.ok is True
    assert response.content == body


async def test_the_timeout_is_the_connections_value_not_the_httpx_default() -> None:
    """An explicit per-provider timeout is the whole point (a hung provider must fail, not hang).
    Assert it reaches the client rather than trusting the constructor."""
    seen: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json=_OK_BODY)

    conn = ProviderConnection(base_url="https://x.test", api_key="k", timeout_seconds=1.5)
    await client_returning(_capture, connections={"openai": conn}).invoke(PROVIDER, REQUEST)
    timeout = seen["timeout"]
    assert isinstance(timeout, dict)
    assert timeout["read"] == 1.5
