"""Deterministic ProviderClient (ADR-0016 Slice 7, Rule 4).

Synthesizes a response instead of calling a real SDK - no network, no credentials, no provider
client library. Validates the port end to end (construction -> executor -> response) without any
of those, none of which are this milestone's question. A real OpenAI/Anthropic/Bedrock/Azure
adapter is provider-abstraction work, out of scope here.
"""

from __future__ import annotations

from gateway.application.ports.providers import InferenceRequest, ProviderResponse
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
        return ProviderResponse(ok=True, content=content, provider=provider.name)
