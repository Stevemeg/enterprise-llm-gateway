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

## Phase 5 M1: the same adapter also implements ``StreamingProviderClient``

One class, two ports. They are separate protocols (see ``ports/streaming.py``) because a provider
that can do one and not the other must be expressible; they live in one adapter because the
endpoint, the credential, the timeout, the status taxonomy and the wire format are identical - and
duplicating them into a second class would be two spellings of one integration, drifting the first
time a status code moved.

``stream`` sends ``"stream": true`` **and** ``"stream_options": {"include_usage": true}``. The
second is not optional politeness: without it an OpenAI-compatible server omits usage from a
streamed response entirely, and this adapter refuses to invent it (identical discipline to
``_usage_from``). Asking for it explicitly is what keeps "the stream ended with no usage" a genuine
provider defect the consumer can act on rather than the normal case.

A ``data:`` line that is not JSON, or whose shape is unrecognisable, ends the stream as a
``SERVER_ERROR`` rather than being skipped. Skipping would silently drop tokens out of the middle
of an answer that the client would then receive, concatenate and believe.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
    ProviderUsage,
)
from gateway.application.ports.streaming import (
    ProviderStreamEvent,
    StreamChunk,
    StreamCompleted,
    StreamFailed,
)
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.logging import get_logger

_logger = get_logger("providers")

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_DEFAULT_PROMPT_KEY = "prompt"
_MODEL_KEY = "model"
_DATA_PREFIX = "data:"
_DONE_SENTINEL = "[DONE]"
_MALFORMED_EVENT = "provider returned a malformed stream event"

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


def _payload_of(line: str) -> str | None:
    """The payload of one ``data:`` frame, or ``None`` for a line that carries no event."""
    stripped = line.strip()
    if not stripped.startswith(_DATA_PREFIX):
        return None
    return stripped[len(_DATA_PREFIX) :].strip()


def _decode(data: str) -> dict[str, Any] | None:
    """Parse one frame's JSON object. ``None`` means malformed - never "skip it and carry on":
    dropping a frame out of the middle of an answer the client will concatenate and believe is
    worse than ending the stream and saying so."""
    try:
        event = json.loads(data)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _delta_from(event: dict[str, Any]) -> str:
    """The incremental text in one streamed chunk, or ``""`` when it carries none.

    An empty answer is not an error: the final ``include_usage`` chunk has an empty ``choices``
    list, and role-only opening deltas carry no content either. Both are ordinary frames to skip,
    which is why this returns a string rather than ``None`` for "nothing here".
    """
    choices = event.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


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

    async def stream(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Stream an OpenAI-compatible ``/chat/completions`` response as owned events."""
        connection = self._connections.get(provider.name)
        if connection is None:
            # Same reasoning as ``invoke``: configuration, not a provider fault, and not retryable.
            _logger.error("provider_not_configured", provider=provider.name)
            yield StreamFailed(
                error="provider has no connection configured",
                error_category=ProviderErrorCategory.AUTHENTICATION,
            )
            return

        body = self._body(provider, request)
        body["stream"] = True
        # Without this an OpenAI-compatible server reports no usage for a streamed call at all,
        # and this adapter will not invent any (see the module docstring).
        body["stream_options"] = {"include_usage": True}

        try:
            async with (
                httpx.AsyncClient(
                    base_url=connection.base_url,
                    timeout=connection.timeout_seconds,
                    transport=self._transport or httpx.AsyncHTTPTransport(retries=0),
                ) as client,
                client.stream(
                    "POST",
                    _CHAT_COMPLETIONS_PATH,
                    json=body,
                    headers={"Authorization": f"Bearer {connection.api_key}"},
                ) as response,
            ):
                if response.status_code >= 400:
                    # Drain so the connection can be released; the body is never surfaced.
                    await response.aread()
                    yield self._stream_failure(
                        provider,
                        _category_for_status(response.status_code),
                        f"provider returned HTTP {response.status_code}",
                    )
                    return
                usage: ProviderUsage | None = None
                async for line in response.aiter_lines():
                    data = _payload_of(line)
                    if data is None:
                        # Blank separators and ``: keep-alive`` comments carry no content.
                        continue
                    if data == _DONE_SENTINEL:
                        yield StreamCompleted(usage=usage)
                        return
                    event = _decode(data)
                    if event is None:
                        yield self._stream_failure(
                            provider, ProviderErrorCategory.SERVER_ERROR, _MALFORMED_EVENT
                        )
                        return
                    reported = _usage_from(event)
                    if reported is not None:
                        usage = reported
                    delta = _delta_from(event)
                    if delta:
                        yield StreamChunk(content=delta)
        except httpx.TimeoutException:
            yield self._stream_failure(
                provider, ProviderErrorCategory.TIMEOUT, "provider call timed out"
            )
            return
        except httpx.HTTPError:
            yield self._stream_failure(
                provider, ProviderErrorCategory.SERVER_ERROR, "provider transport error"
            )
            return
        # Fell off the end of the body without ``[DONE]``. No terminal event is emitted: the
        # consumer must not be able to mistake a truncated stream for a completed one.

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

    @staticmethod
    def _stream_failure(
        provider: ProviderDescriptor, category: ProviderErrorCategory, message: str
    ) -> StreamFailed:
        """The streaming twin of ``_failure``: one exit, so no provider text can leak."""
        _logger.warning("provider_stream_failed", provider=provider.name, category=category.value)
        return StreamFailed(error=message, error_category=category)
