"""The first real ``ProviderClient``: an OpenAI-compatible HTTP adapter (ADR-0003, Slice 19).

ADR-0003 chose "a first-party Provider Port + Adapter contract" and named a **generic
OpenAI-compatible adapter** as the one that "covers self-hosted/open-weight models (FR-024)". It is
also the broadest first adapter available: OpenAI, Azure OpenAI, vLLM, Ollama, TGI and most
gateways speak ``POST /chat/completions`` with the same request and response shape. One adapter,
several provider types, no core change - which is the open/closed property FR-026 asks for.

Everything provider-specific stops here. The SDK (``httpx``), the wire format, the status-code
taxonomy, the credentials and the timeouts are all inside this module; what leaves it is a
``ProviderResponse``, which is the same type ``InMemoryProviderClient`` returns.

## What this adapter does not do, deliberately

* **It does not retry.** Reflection owns retry (Slice 11, ``ReflectiveExecutor`` +
  ``RetryPolicy``), including the attempt bound and the backoff. An adapter that also retried
  would multiply the two limits together and spend a tenant's money three times over for what the
  policy believed was one attempt. ``httpx`` transports are therefore constructed with
  ``retries=0`` - stated explicitly rather than left to a default that could change.
* **It does not choose a provider.** ``ProviderDescriptor`` arrives already selected. If the
  descriptor names a provider this deployment has no connection configured for, that is a
  configuration failure reported as one, not an invitation to pick another.
* **It does not raise for a provider-level failure.** ``ProviderClient``'s contract is "must not
  raise for a provider-level failure - return ``ok=False``", so every transport error, timeout and
  HTTP error status becomes a classified ``ProviderResponse``. An SDK exception never escapes.
* **It does not invent usage.** A response that omits ``usage`` yields ``usage=None``, which
  ``CostAccountant`` turns into ``MissingUsageError`` at settlement. ``retry_policy.py`` already
  documents that this is the intended path for malformed provider output - "a defect a human must
  fix", never a retry - so this adapter follows that decision rather than making a second one.

## Timeouts are explicit and per provider

``ProviderConnection.timeout_seconds`` is required, not defaulted to ``httpx``'s own. A hung
provider must fail as a ``TIMEOUT`` - which reflection *will* retry - rather than occupying the
request path indefinitely.

## Credentials

The API key arrives already resolved from the secrets manager by the composition root (ADR-0011);
this module never reads an environment variable and holds no default. The key is used to build one
``Authorization`` header and is never logged, never placed in an error string, and never returned
in a ``ProviderResponse`` - the only text this adapter ever attaches to a failure is its own, or a
provider error body that the delivery layer is already forbidden to echo (Slice 17).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
    ProviderUsage,
)
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.logging import get_logger

_logger = get_logger("providers")

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_DEFAULT_PROMPT_KEY = "prompt"
_MODEL_KEY = "model"

#: HTTP status -> canonical category (ADR-0003's "normalized error taxonomy"). Anything not named
#: here falls back by class: 5xx is a server error, any other 4xx is an invalid request.
_STATUS_CATEGORIES: dict[int, ProviderErrorCategory] = {
    400: ProviderErrorCategory.INVALID_REQUEST,
    401: ProviderErrorCategory.AUTHENTICATION,
    403: ProviderErrorCategory.AUTHENTICATION,
    404: ProviderErrorCategory.INVALID_REQUEST,
    408: ProviderErrorCategory.TIMEOUT,
    422: ProviderErrorCategory.INVALID_REQUEST,
    429: ProviderErrorCategory.RATE_LIMITED,
}


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    """How to reach one provider. Deployment configuration, never routing data.

    This is why ``ProviderDescriptor`` was not widened: the descriptor travels through
    ``RoutingExecution`` and into the decision record, and an endpoint and an API key have no
    business being there. The catalog decides *which* provider; this decides *how to reach it*,
    and the two meet only inside this adapter.
    """

    base_url: str
    api_key: str
    timeout_seconds: float


def _category_for_status(status: int) -> ProviderErrorCategory:
    named = _STATUS_CATEGORIES.get(status)
    if named is not None:
        return named
    if status >= 500:
        return ProviderErrorCategory.SERVER_ERROR
    return ProviderErrorCategory.INVALID_REQUEST


def _usage_from(payload: dict[str, Any]) -> ProviderUsage | None:
    """Extract canonical usage. ``None`` when the provider reported none - never a fabricated zero.

    Zero and "not reported" are different facts, and ``CostAccountant`` is built to tell them
    apart (``MissingUsageError`` exists for exactly this). A malformed usage block is treated as
    absent for the same reason: guessing would launder a provider defect into a billable number.
    """
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return None
    prompt, completion = raw.get("prompt_tokens"), raw.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return ProviderUsage(prompt_tokens=prompt, completion_tokens=completion)


def _content_from(payload: dict[str, Any]) -> Any:
    """The assistant message, or the whole body when the shape is unfamiliar.

    Falling back to the body rather than to ``None`` keeps a slightly-off-spec but successful
    response usable, which matters for the self-hosted servers FR-024 targets.
    """
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and "content" in message:
                return message["content"]
    return payload


class OpenAiCompatibleProviderClient:
    """Calls an OpenAI-compatible ``/chat/completions`` endpoint for the provider it is given."""

    def __init__(
        self,
        connections: dict[str, ProviderConnection],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """``connections`` is keyed by ``ProviderDescriptor.name``.

        ``transport`` is injectable so contract tests can exercise real ``httpx`` request and
        response handling - status codes, headers, JSON decoding, timeouts - against scripted
        responses, with no network and no provider credits spent (ADR-0003's "contract tests
        replaying recorded provider fixtures").
        """
        self._connections = dict(connections)
        self._transport = transport

    def _body(self, provider: ProviderDescriptor, request: InferenceRequest) -> dict[str, Any]:
        """Translate the internal payload into the provider's wire format.

        The model comes from the *descriptor*, not from the caller's payload: the model is part of
        what routing selected, and letting an inbound field override it would let a caller route
        itself past every decision the agents made.
        """
        payload = dict(request.payload)
        prompt = payload.get(_DEFAULT_PROMPT_KEY, "")
        body: dict[str, Any] = {
            _MODEL_KEY: provider.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        return body

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        connection = self._connections.get(provider.name)
        if connection is None:
            # Configuration, not a provider fault. AUTHENTICATION is the closest honest category
            # and, importantly, is NOT retryable - retrying a provider we cannot reach at all
            # would burn the whole attempt budget on a misconfiguration.
            _logger.error("provider_not_configured", provider=provider.name)
            return ProviderResponse(
                ok=False,
                error="provider has no connection configured",
                provider=provider.name,
                error_category=ProviderErrorCategory.AUTHENTICATION,
            )

        try:
            async with httpx.AsyncClient(
                base_url=connection.base_url,
                timeout=connection.timeout_seconds,
                # Reflection owns retry (Slice 11). See the module docstring.
                transport=self._transport or httpx.AsyncHTTPTransport(retries=0),
            ) as client:
                response = await client.post(
                    _CHAT_COMPLETIONS_PATH,
                    json=self._body(provider, request),
                    headers={"Authorization": f"Bearer {connection.api_key}"},
                )
        except httpx.TimeoutException:
            return self._failure(provider, ProviderErrorCategory.TIMEOUT, "provider call timed out")
        except httpx.HTTPError:
            # Connect/read/protocol errors. The exception text can contain the URL, so it is not
            # propagated - the category is what any consumer actually acts on.
            return self._failure(
                provider, ProviderErrorCategory.SERVER_ERROR, "provider transport error"
            )

        if response.status_code >= 400:
            return self._failure(
                provider,
                _category_for_status(response.status_code),
                f"provider returned HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError:
            return self._failure(
                provider, ProviderErrorCategory.SERVER_ERROR, "provider returned a malformed body"
            )
        if not isinstance(payload, dict):
            return self._failure(
                provider, ProviderErrorCategory.SERVER_ERROR, "provider returned a malformed body"
            )

        return ProviderResponse(
            ok=True,
            content=_content_from(payload),
            provider=provider.name,
            usage=_usage_from(payload),
        )

    @staticmethod
    def _failure(
        provider: ProviderDescriptor, category: ProviderErrorCategory, message: str
    ) -> ProviderResponse:
        """Every failure exits through here, so none can accidentally carry provider text.

        ``message`` is always one of this module's own constant strings - never a provider body,
        never an exception's ``str()``, never a URL, and never anything derived from the API key.
        """
        _logger.warning("provider_call_failed", provider=provider.name, category=category.value)
        return ProviderResponse(
            ok=False, error=message, provider=provider.name, error_category=category
        )
