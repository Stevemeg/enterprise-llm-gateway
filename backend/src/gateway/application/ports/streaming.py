"""Streaming provider seam (Phase 5 Milestone 1) - a **capability-owned** port, not Tier-1.

Tier 1 is untouched, and that is this milestone's central result rather than an assumption:
``RoutingDecision``, ``RoutingExecution``, ``PipelineStage`` and ``BaseAgent`` are byte-identical
after streaming landed. A stream is *how a provider delivers one already-routed call*; it is not a
new routing concept, not a new admission concept and not a new agent concept, so none of those
seams has anything to say about it.

## Why a separate port rather than a method on ``ProviderClient`` (Rule 5)

``ProviderClient.invoke`` returns a **completed** ``ProviderResponse``. Four designs were
considered before any code was written:

* **(A) a separate, capability-owned streaming port** - chosen, see below;
* **(B) an additive ``stream`` method on ``ProviderClient``** - rejected. ``ProviderClient`` is a
  ``Protocol``, so adding a method makes *every* implementation that does not have it stop
  satisfying the seam. Two of the three existing implementations exist precisely to validate the
  non-streaming shape (Rule 4), and neither has a consumer that wants to stream. Rule 5's third
  test - "why does the change not belong in the consumer instead" - is answered here by "it does
  not belong in the *protocol* at all": nothing forces the two capabilities to be one interface,
  and fusing them would mean a provider that can only do one of them cannot be modelled;
* **(C) widening ``ProviderResponse``/``InferenceRequest``** - rejected. A completed response and a
  stream in progress are different facts, and a ``ProviderResponse`` that sometimes carries an
  iterator would make "did this call finish" unanswerable from the type;
* **(D) widening a Tier-1 protocol** - rejected, and never needed. Nothing here is a routing,
  admission or agent concern.

**Active consumer:** ``application/streaming/streaming_coordinator.py`` - the only component that
consumes incremental provider output. It cannot be implemented against ``invoke`` at all, because
``invoke`` returns only after the provider is finished, which is exactly the limitation streaming
exists to remove.

Capability-owned, additive, and orthogonal to the existing port: this is a **new seam** (Rule 2 -
protocol here, implementation behind it, CI enforcement in ``pyproject.toml``), not the growth of
an existing one, so no Tier-1 contract moved.

## Owned events, not provider wire format (Rule 3)

A provider's SSE frames, its ``delta`` shape, its ``[DONE]`` sentinel and its usage block stop at
the adapter. What crosses this seam is the three-member union below - the minimum a consumer must
distinguish to be correct about money:

* ``StreamChunk``     - output was produced, and (once handed on) has escaped to the client;
* ``StreamCompleted`` - the provider finished normally; ``usage`` is what it *reported*, never a
  reconstruction. ``None`` means it reported none, which is a defect a human must fix, not a zero
  (identical discipline to ``ProviderResponse.usage`` / ``CostAccountant.MissingUsageError``);
* ``StreamFailed``    - the provider failed. Failure is **data, not an exception**, matching
  ``ProviderClient``'s own contract, so a consumer's ``async for`` never has to double as an
  exception handler to stay correct about releasing a budget hold.

There is deliberately no ``StreamStarted`` event: "started" is already observable as the first
event of any kind, and a second spelling of one fact is two sources of truth (Rule 3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderUsage,
)
from gateway.application.routing.catalog import ProviderDescriptor


@dataclass(frozen=True, slots=True)
class StreamChunk:
    """One incremental piece of generated output.

    ``content`` is text because that is what every consumer in this milestone concatenates - the
    response cache stores it, and the delivery layer frames it. Tool-call and structured-output
    deltas are real provider concepts this type deliberately does not model until something reads
    them (Rule 5).
    """

    content: str


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    """The provider ended the stream normally.

    ``usage`` is ``None`` exactly when the provider reported none. Accounting must treat that as
    "nothing we can account for", never as zero-cost usage - the same distinction
    ``ProviderResponse.usage`` draws, for the same reason.
    """

    usage: ProviderUsage | None = None


@dataclass(frozen=True, slots=True)
class StreamFailed:
    """The provider failed, before or after producing output.

    ``error`` is always adapter-authored text, never a provider body (the adapter's own
    ``_failure`` discipline), and ``error_category`` reuses the existing closed vocabulary so the
    circuit breaker classifies a streamed failure exactly as it classifies a unary one.
    """

    error: str
    error_category: ProviderErrorCategory | None = None


#: What a ``StreamingProviderClient`` may emit. A well-behaved stream is zero or more
#: ``StreamChunk`` followed by exactly one terminal event (``StreamCompleted`` or ``StreamFailed``).
#: A stream that simply stops without a terminal event is a malformed stream, and the consumer -
#: not this port - decides what that means for money (see ``StreamingCoordinator``).
ProviderStreamEvent = StreamChunk | StreamCompleted | StreamFailed

#: What the application hands to the delivery layer. Narrower than ``ProviderStreamEvent`` on
#: purpose: normal completion is the iterator ending, because a delivery layer that had to
#: distinguish "completed" from "stopped" would be re-deciding a question the coordinator has
#: already answered (and already settled money on).
InferenceStreamEvent = StreamChunk | StreamFailed


@runtime_checkable
class StreamingProviderClient(Protocol):
    """Executes one inference request against one resolved provider, incrementally."""

    def stream(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Open a stream. Must not raise for a provider-level failure - yield ``StreamFailed``.

        Deliberately not ``async def``: an implementation is an async generator, so the caller
        writes ``async for event in client.stream(...)`` and the connection is opened lazily on
        first iteration. Closing the iterator (client disconnect, cancellation) must abort the
        upstream call rather than leaving it running.
        """
        ...
