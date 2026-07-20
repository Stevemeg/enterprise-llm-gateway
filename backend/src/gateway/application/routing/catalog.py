"""Provider catalog - what the routing engine may choose between (ADR-0016 Slice 6).

The catalog answers one question: which providers exist for this organization. It does not rank
them, score them or know why one would be preferred, because that is selection intelligence and
``ProviderAgent`` owns it. Keeping the catalog dumb is what stops the engine from quietly
becoming a second router.

A ``Protocol`` rather than a bare class because the in-memory catalog is a starting point, not the
design: a database- or config-backed catalog must substitute without the engine noticing. There
is exactly one implementation today and no speculative second one (Rule 2).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """A routable provider. Carries identity only - no credentials, no endpoint, no client."""

    name: str
    model: str
    region: str = "global"


@runtime_checkable
class ProviderCatalog(Protocol):
    """Which providers an organization may route to."""

    async def candidates(self, organization_id: UUID) -> tuple[ProviderDescriptor, ...]:
        """Providers available to this tenant. Empty is a valid answer, never an error."""
        ...

    async def get(self, organization_id: UUID, name: str) -> ProviderDescriptor | None:
        """Resolve one provider by name. ``None`` when absent so callers fail closed."""
        ...


class InMemoryProviderCatalog(ProviderCatalog):
    """Static per-tenant catalog.

    Tenant-keyed rather than global: two organizations may legitimately be entitled to different
    providers, and a catalog that ignored the tenant would offer one tenant's entitlements to
    another - the same isolation boundary RLS enforces in storage.
    """

    def __init__(
        self, providers: Mapping[UUID, Iterable[ProviderDescriptor]] | None = None
    ) -> None:
        self._providers: dict[UUID, tuple[ProviderDescriptor, ...]] = {
            org: tuple(items) for org, items in (providers or {}).items()
        }

    def register(self, organization_id: UUID, providers: Sequence[ProviderDescriptor]) -> None:
        self._providers[organization_id] = tuple(providers)

    async def candidates(self, organization_id: UUID) -> tuple[ProviderDescriptor, ...]:
        return self._providers.get(organization_id, ())

    async def get(self, organization_id: UUID, name: str) -> ProviderDescriptor | None:
        for descriptor in self._providers.get(organization_id, ()):
            if descriptor.name == name:
                return descriptor
        return None
