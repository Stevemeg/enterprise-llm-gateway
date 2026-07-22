"""Provider execution seam (ADR-0016 Slice 7) - a **capability-owned** port, not a Tier-1 protocol.

Tier 1 is untouched by this milestone (Rule 5 not triggered): ``RoutingDecision`` and
``RoutingExecution`` are unchanged, and neither carries a request payload. This port exists so
``ProviderExecutor`` can turn a routing selection into an actual call without choosing an SDK,
which is what keeps it a capability layer rather than a rewrite of the routing seam.

``InferenceRequest`` and ``ProviderResponse`` are typed here, not left as a bare ``dict`` (Rule 3):
``ProviderExecutor`` and every ``ProviderClient`` implementation must agree on their shape, and
that agreement would drift silently if it were a convention instead of a type.

## Why this port has no null implementation

Rule 4 asks for a working implementation, not a trivial one that would validate nothing about the
shape of a provider call. Validation here comes from two real implementations instead:
``InMemoryProviderClient`` (deterministic, synthesizes a response) and ``FakeProviderClient``
(scriptable, exercises the failure path) - see ``adapters/providers/``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from gateway.application.routing.catalog import ProviderDescriptor


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    """The inbound request payload - what to send a provider, independent of how it was routed.

    Kept separate from ``RoutingDecision``/``RoutingExecution`` deliberately: those explain a
    routing outcome, this carries what to execute. Merging them would mean every future reader of
    a routing record - metrics, audit, debugging - also had to know the request shape.
    """

    correlation_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Outcome of a provider call. Failure is data, not an exception (mirrors ``McpResult``)."""

    ok: bool
    content: Any = None
    error: str | None = None
    provider: str = ""


@runtime_checkable
class ProviderClient(Protocol):
    """Executes one inference request against one resolved provider."""

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        """Call the provider. Must not raise for a provider-level failure - return ``ok=False``."""
        ...
