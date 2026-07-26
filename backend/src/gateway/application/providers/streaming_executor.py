"""StreamingProviderExecutor - turns a resolved selection into a provider *stream* (Phase 5 M1).

The streaming counterpart of ``ProviderExecutor``, and deliberately its exact analogue: it owns the
provider-call boundary and the latency measurement taken across it, and it owns nothing else. It
does not route, does not price, does not reserve, does not settle, does not cache and does not
retry - each of those already has an owner, and this class can reach none of them (import-linter:
``provider execution does not depend on accounting``, unchanged from Slice 8 and now covering this
module too).

## Why it takes a ``ProviderDescriptor``, not a ``RoutingExecution``

``ProviderExecutor.execute`` accepts the whole ``RoutingExecution`` because it must handle the
unrouted case (it returns the "not routed" response rather than calling anybody). This class is
handed the already-resolved descriptor instead, so "the stream executor cannot route" is
structural rather than reviewed: it never sees a ``RoutingDecision`` at all, and there is no
unrouted branch here to keep correct - ``StreamingCoordinator`` refuses an unrouted request before
this class is reached, exactly as the routing architecture intends.

## One metric, recorded once, at the end of the stream

``record_provider_call`` reports **total stream duration**, so a streamed call and a unary call are
comparable in the same time series. Time-to-first-event is a genuinely different and useful number,
and is deliberately *not* recorded: no consumer reads it yet, and a second histogram added on
speculation is exactly what Rule 5 exists to prevent. The outcome label reuses the existing closed
vocabulary - ``ok`` for a normal completion, the error category for a failure, ``unclassified``
for a stream that ends without saying which it was. Recording happens in ``finally``, so a client
that disconnects mid-stream still produces the measurement rather than silently vanishing from the
provider's time series.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from gateway.application.ports.providers import InferenceRequest
from gateway.application.ports.streaming import (
    ProviderStreamEvent,
    StreamCompleted,
    StreamFailed,
    StreamingProviderClient,
)
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.metrics import UNCLASSIFIED, record_provider_call


async def aclose_stream(stream: AsyncIterator[ProviderStreamEvent]) -> None:
    """Close a provider stream if it can be closed, so the upstream call is actually aborted.

    ``AsyncIterator`` does not promise ``aclose``; every implementation in this project is an async
    generator, which does. Dropping the reference instead would leave the abort to the event loop's
    async-generator finalization, whose timing is not deterministic - and an upstream HTTP
    connection that stays open after the client has gone is a leaked provider call being paid for.
    """
    closer = getattr(stream, "aclose", None)
    if closer is not None:
        await closer()


class StreamingProviderExecutor:
    """Streams one inference request against one already-selected provider."""

    def __init__(self, client: StreamingProviderClient) -> None:
        self._client = client

    async def stream(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        """Yield the provider's events verbatim, measuring the call around them."""
        started = time.monotonic()
        outcome = UNCLASSIFIED
        upstream = self._client.stream(provider, request)
        try:
            async for event in upstream:
                if isinstance(event, StreamCompleted):
                    outcome = "ok"
                elif isinstance(event, StreamFailed):
                    outcome = (
                        event.error_category.value
                        if event.error_category is not None
                        else UNCLASSIFIED
                    )
                yield event
        finally:
            await aclose_stream(upstream)
            record_provider_call(
                provider=provider.name,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
            )
