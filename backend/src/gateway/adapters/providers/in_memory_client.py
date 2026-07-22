"""Deterministic ProviderClient (ADR-0016 Slice 7, Rule 4; usage added Slice 8).

Synthesizes a response instead of calling a real SDK - no network, no credentials, no provider
client library. Validates the port end to end (construction -> executor -> response) without any
of those, none of which are this milestone's question. A real OpenAI/Anthropic/Bedrock/Azure
adapter is provider-abstraction work, out of scope here.

``ProviderUsage`` is likewise synthesized, not tokenized: a deterministic function of the request
payload's serialized length, explicitly not a real tokenizer. It exists so this adapter can
validate the Slice-8 usage seam end to end without depending on a real provider or a real
tokenizer, neither of which this milestone introduces.
"""

from __future__ import annotations

from gateway.application.ports.providers import InferenceRequest, ProviderResponse, ProviderUsage
from gateway.application.routing.catalog import ProviderDescriptor


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
        # Not a tokenizer - a deterministic stand-in so usage-dependent code has something real
        # to consume. prompt_tokens scales with payload size; completion_tokens is a fixed
        # fraction of it, both floored at 1 so an empty payload still reports nonzero usage.
        prompt_tokens = max(1, len(str(dict(request.payload))) // 4)
        completion_tokens = max(1, prompt_tokens // 2)
        usage = ProviderUsage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        return ProviderResponse(ok=True, content=content, provider=provider.name, usage=usage)
