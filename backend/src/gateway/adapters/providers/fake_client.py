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
    """Scripted responses keyed by provider name, plus a call log for assertions.

    ``sequence`` (Slice 11) scripts responses *per call* rather than per provider, so a caller can
    exercise "fails twice, then succeeds" - the shape a retry layer exists to handle, and one a
    provider-keyed dict cannot express because it answers every call identically. The final entry
    repeats once the sequence is exhausted, so a policy that keeps retrying keeps seeing the same
    terminal state rather than silently falling through to different behaviour.
    """

    responses: dict[str, ProviderResponse] = field(default_factory=dict)
    sequence: list[ProviderResponse] = field(default_factory=list)
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
        if self.sequence:
            index = min(len(self.calls), len(self.sequence)) - 1
            return self.sequence[index]
        scripted = self.responses.get(provider.name)
        if scripted is None:
            return ProviderResponse(
                ok=False,
                error=f"no scripted response for {provider.name!r}",
                provider=provider.name,
            )
        return scripted
