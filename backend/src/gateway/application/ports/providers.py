"""Provider execution seam (ADR-0016 Slice 7, widened Slice 8) - a **capability-owned** port, not
a Tier-1 protocol.

Tier 1 is untouched (Rule 5 not triggered against Tier 1): ``RoutingDecision`` and
``RoutingExecution`` remain unchanged, and neither carries a request payload or usage. This port
exists so ``ProviderExecutor`` can turn a routing selection into an actual call without choosing
an SDK, which is what keeps it a capability layer rather than a rewrite of the routing seam.

``InferenceRequest`` and ``ProviderResponse`` are typed here, not left as a bare ``dict`` (Rule 3):
``ProviderExecutor`` and every ``ProviderClient`` implementation must agree on their shape, and
that agreement would drift silently if it were a convention instead of a type.

## Why this port has no null implementation

Rule 4 asks for a working implementation, not a trivial one that would validate nothing about the
shape of a provider call. Validation here comes from two real implementations instead:
``InMemoryProviderClient`` (deterministic, synthesizes a response) and ``FakeProviderClient``
(scriptable, exercises the failure path) - see ``adapters/providers/``.

## Rule 5 event (Slice 8): ``ProviderUsage`` added to ``ProviderResponse``

**Active consumer:** ``application/accounting/cost_accountant.py`` (new in Slice 8) - it converts
provider-reported usage into deterministic monetary cost and has no other way to learn how many
tokens a call consumed.

**Why the existing protocol was insufficient:** ``ProviderResponse`` carried no usage information
at all; cost accounting is impossible without it.

**Why the change does not belong in the consumer instead:** usage is reported *by the provider, at
the moment of the call* - only a ``ProviderClient`` implementation observes it. The accounting
layer receiving the response has no independent way to reconstruct token counts after the fact,
so the field must travel with the response, not be bolted on downstream.

This is a **capability-owned** port, not Tier-1, so this is a Rule 5 event recorded in the
evidence log - not a new ADR (ADR-0016's Rule 2 sequence governs a seam's *birth*; this is an
existing capability-owned seam evolving under Rule 5, the same shape as ``PipelineStage`` gaining
``@runtime_checkable`` in Slice 2). The field is additive and optional (default ``None``): every
Slice 7 construction of ``ProviderResponse`` remains valid unchanged.
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
class ProviderUsage:
    """Provider-reported token usage for one call (Rule 3: shared by every ``ProviderClient``
    implementation and by cost accounting; a convention here would drift silently).

    Only prompt/completion tokens exist because only those are consumed anywhere in this project
    yet (Rule 5) - cached-token, image, audio and tool-call usage are real provider concepts this
    type deliberately does not model until something reads them.
    """

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Outcome of a provider call. Failure is data, not an exception (mirrors ``McpResult``).

    ``usage`` is ``None`` exactly when no usage was ever incurred - a provider failure before any
    tokens were consumed. Cost accounting must treat that as "nothing to account for", never as
    zero-cost usage: those are different facts (see ``MissingUsageError``).
    """

    ok: bool
    content: Any = None
    error: str | None = None
    provider: str = ""
    usage: ProviderUsage | None = None


@runtime_checkable
class ProviderClient(Protocol):
    """Executes one inference request against one resolved provider."""

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        """Call the provider. Must not raise for a provider-level failure - return ``ok=False``."""
        ...
