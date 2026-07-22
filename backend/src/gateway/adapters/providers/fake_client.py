"""Scriptable ProviderClient double (ADR-0016 Slice 7, Rule 4).

The second implementation: proves ``ProviderClient`` supports more than one backend with no
protocol change, and gives ``ProviderExecutor`` a way to exercise failure and latency paths that
``InMemoryProviderClient`` - which always succeeds - cannot. No networking, no SDK, no retries;
same posture as ``adapters/mcp/fake_server.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gateway.application.ports.providers import InferenceRequest, ProviderResponse
from gateway.application.routing.catalog import ProviderDescriptor


@dataclass
class FakeProviderClient:
    """Scripted responses keyed by provider name, plus a call log for assertions."""

    responses: dict[str, ProviderResponse] = field(default_factory=dict)
    unreachable: bool = False
    calls: list[tuple[ProviderDescriptor, InferenceRequest]] = field(default_factory=list)

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        self.calls.append((provider, request))
        if self.unreachable:
            return ProviderResponse(
                ok=False, error="simulated provider unreachable", provider=provider.name
            )
        scripted = self.responses.get(provider.name)
        if scripted is None:
            return ProviderResponse(
                ok=False,
                error=f"no scripted response for {provider.name!r}",
                provider=provider.name,
            )
        return scripted
