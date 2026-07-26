"""The fail-closed ``ProviderClient`` for a deployment with no provider connections (Phase 5 M2).

## The defect this exists to close

Until M2 the composition root fell back to ``InMemoryProviderClient`` whenever no provider
connection was configured. That client's own docstring is "Echoes the request back as the response
content. **Always succeeds**" - and it synthesizes ``ProviderUsage``. So a production deployment
that had a seeded provider catalog but had not been told how to *reach* any provider would answer
every request 200, with fabricated content, and **book real spend against the tenant's budget for
an inference that never happened**. Nothing failed, nothing alerted, and the numbers looked right.

The fallback is therefore this class instead: it never produces content, never reports usage, and
never returns ``ok=True``. A misconfigured deployment now refuses, loudly and consistently, which
is the only honest answer to "I was asked to call a provider I have no way to reach".

## Why a refusal rather than a startup failure

Refusing to start would be the stronger signal, and it was considered. It is wrong here for a
specific reason rather than for convenience: whether a deployment has anything to route to is a
**per-tenant, runtime** fact (the catalog is tenant-scoped and read from the database - Slice 19),
not a startup fact. A gateway serving ten tenants, nine of them correctly configured, must not
refuse to boot because the tenth has a provider row with no matching connection. Startup-time
fail-fast is already applied to the things that *are* startup facts: a configured provider whose
credential cannot be resolved, or which has no ``base_url``, still fails startup
(``_build_provider_connections``), and ``allow_fake_provider_client`` is rejected outright in
production by the settings validator.

## Why ``AUTHENTICATION``

Not because a credential was rejected, but because that is the category
``OpenAiCompatibleProviderClient`` already assigns to "this provider has no connection
configured", and it is deliberately **not** retryable - retrying a provider the deployment cannot
reach at all would burn the whole attempt budget on a misconfiguration. Two spellings of one fact
would drift (Rule 3), so this reuses that one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderErrorCategory,
    ProviderResponse,
)
from gateway.application.ports.streaming import ProviderStreamEvent, StreamFailed
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.observability.logging import get_logger

_logger = get_logger("providers")

#: The one message either entry point may return. Names no provider internals and no configuration
#: key: an operator finds the detail in the log line below, a caller learns only that it failed.
UNCONFIGURED_ERROR = "no provider connection is configured for this deployment"


class UnconfiguredProviderClient:
    """Refuses every call. Satisfies ``ProviderClient`` and ``StreamingProviderClient`` alike."""

    def _refuse(self, provider: ProviderDescriptor) -> None:
        _logger.error(
            "provider_client_unconfigured",
            provider=provider.name,
            model=provider.model,
            remedy="set GATEWAY_PROVIDERS__<NAME>__BASE_URL and __API_KEY_REF",
        )

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        self._refuse(provider)
        # No content and no usage, so nothing downstream can settle a cost for this call: the
        # accounting layer's ``MissingUsageError`` discipline is never even reached, because
        # ``ok=False`` releases the reservation instead.
        return ProviderResponse(
            ok=False,
            error=UNCONFIGURED_ERROR,
            provider=provider.name,
            error_category=ProviderErrorCategory.AUTHENTICATION,
        )

    async def stream(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> AsyncIterator[ProviderStreamEvent]:
        self._refuse(provider)
        yield StreamFailed(
            error=UNCONFIGURED_ERROR, error_category=ProviderErrorCategory.AUTHENTICATION
        )
