"""Deterministic ProviderClient (ADR-0016 Slice 7, Rule 4; usage added Slice 8).

Synthesizes a response instead of calling a real SDK - no network, no credentials, no provider
client library. Validates the port end to end (construction -> executor -> response) without any
of those, none of which are this milestone's question. A real OpenAI/Anthropic/Bedrock/Azure
adapter is provider-abstraction work, out of scope here.

``ProviderUsage`` is likewise synthesized, not tokenized: a deterministic function of the request
payload's serialized length, explicitly not a real tokenizer. It exists so this adapter can
validate the Slice-8 usage seam end to end without depending on a real provider or a real
tokenizer, neither of which this milestone introduces.

**This adapter fabricates successful inference and must never be the production default.** Since
Phase 5 M2 it is reachable only when a deployment opts in explicitly
(``GATEWAY_ALLOW_FAKE_PROVIDER_CLIENT=true``, forbidden in production); an unconfigured deployment
gets ``UnconfiguredProviderClient``, which fails closed instead.

Phase 5 M1 adds ``stream`` so the streaming seam has a non-HTTP implementation to be exercised
against. It chunks the same synthesized answer; the usage it reports is identical to ``invoke``'s,
so a streamed and a unary call for the same payload settle to the same cost.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from gateway.application.ports.providers import InferenceRequest, ProviderResponse, ProviderUsage
from gateway.application.ports.streaming import (
    ProviderStreamEvent,
    StreamChunk,
    StreamCompleted,
)
from gateway.application.routing.catalog import ProviderDescriptor

#: How many pieces a synthesized answer is delivered in. More than one, so a consumer that only
#: works for single-chunk streams fails here rather than in production.
_CHUNKS = 3


def _synthesized_usage(request: InferenceRequest) -> ProviderUsage:
    """Not a tokenizer - a deterministic stand-in so usage-dependent code has something real to
    consume. prompt_tokens scales with payload size; completion_tokens is a fixed fraction of it,
    both floored at 1 so an empty payload still reports nonzero usage."""
    prompt_tokens = max(1, len(str(dict(request.payload))) // 4)
    return ProviderUsage(prompt_tokens=prompt_tokens, completion_tokens=max(1, prompt_tokens // 2))


class InMemoryProviderClient:
    """Echoes the request back as the response content. Always succeeds."""

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        content = {
            "provider": provider.name,
            "model": provider.model,
            "echo": dict(request.payload),
        }
        usage = _synthesized_usage(request)
        return ProviderResponse(ok=True, content=content, provider=provider.name, usage=usage)

    async def stream(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Deliver the same synthesized answer in pieces, then report usage. Always succeeds."""
        text = f"{provider.name}/{provider.model}: {dict(request.payload)}"
        size = max(1, -(-len(text) // _CHUNKS))  # ceiling division; never a zero-width slice
        for start in range(0, len(text), size):
            yield StreamChunk(content=text[start : start + size])
        yield StreamCompleted(usage=_synthesized_usage(request))
