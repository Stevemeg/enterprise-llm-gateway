"""Durable, tenant-scoped ``ProviderCatalog`` backed by PostgreSQL (ADR-0003, Slice 19).

The second implementation of the Slice-6 port, and the first with real storage. The catalog still
answers exactly one question - *which providers may this organization route to* - and still ranks,
scores and prefers nothing: that is selection intelligence and ``ProviderAgent`` owns it. Reading
from a database changes where the answer comes from, not what the question is.

## Read-through, not a startup snapshot

Every call queries. FR-028 requires providers and models to be enabled and disabled at runtime
without a redeploy, and a catalog cached at startup would silently ignore that - an operator
disabling a misbehaving provider would keep routing to it until the next restart. The cost is one
small indexed query per routing attempt, which is recorded as known debt rather than pre-optimised
away behind a cache nothing has asked for.

## One descriptor per provider, and why

``AgentOrchestratedRoutingEngine`` passes the runtime ``candidates=tuple(d.name for d in ...)`` and
later resolves the selection back with ``get(organization_id, name)``. The runtime's candidate
vocabulary is therefore the **provider name**, and two descriptors sharing a name would make that
resolution ambiguous - the engine would raise ``RoutingIntegrityError`` or, worse, silently take
whichever came first.

So a provider with several enabled models is offered once, with its first model by name. That is a
deterministic, documented choice, not an arbitrary one - and it is deliberately *not* a selection
heuristic. Choosing among a provider's models (by alias, quality tier or context window, all of
which the schema carries) is routing intelligence with no consumer today; inventing one here would
put provider selection in the component whose entire purpose is to not have any.

## Failure semantics

Unlike the permission resolver, this port does not promise never to raise: ``candidates`` returning
an empty tuple is a *meaningful* answer that flows into the runtime as ``NO_CANDIDATE`` and refuses
the request with an explanation. Converting a database outage into that same empty tuple would
report "you have no providers configured" for what is actually "we cannot tell", so a failure is
raised as ``ProviderCatalogUnavailableError`` instead. It reaches the routing stage, which fails
the request closed - an outage must not look like a configuration state.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from gateway.adapters.persistence.catalog_tables import model, provider
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.routing.catalog import ProviderCatalog, ProviderDescriptor

_DEFAULT_REGION = "global"


class ProviderCatalogUnavailableError(RuntimeError):
    """The provider catalog could not be read. Distinct from "this tenant has no providers"."""


class SqlProviderCatalog(ProviderCatalog):
    """Reads routable providers from the tenant's ``provider``/``model`` rows."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def _descriptors(self, organization_id: UUID) -> tuple[ProviderDescriptor, ...]:
        # Both ``is_enabled`` flags are required (FR-028): disabling a provider must disable every
        # model behind it, and disabling one model must not remove the provider if another is
        # still enabled. Ordered so the per-provider pick below is deterministic.
        query = (
            select(
                provider.c.name.label("provider_name"),
                provider.c.region.label("region"),
                model.c.name.label("model_name"),
            )
            .select_from(provider.join(model, model.c.provider_id == provider.c.id))
            .where(
                provider.c.organization_id == organization_id,
                model.c.organization_id == organization_id,
                provider.c.is_enabled.is_(True),
                model.c.is_enabled.is_(True),
            )
            .order_by(provider.c.name.asc(), model.c.name.asc())
        )
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                rows = (await uow.session.execute(query)).mappings().all()
        except (SQLAlchemyError, OSError) as exc:
            # Only the exception TYPE: SQLAlchemy messages can quote bound parameters (NFR-SEC03).
            raise ProviderCatalogUnavailableError(type(exc).__name__) from exc

        # First model per provider, by name. The query is already ordered, so "first seen wins"
        # is deterministic across runs and across connections.
        seen: dict[str, ProviderDescriptor] = {}
        for row in rows:
            name = row["provider_name"]
            if name in seen:
                continue
            seen[name] = ProviderDescriptor(
                name=name,
                model=row["model_name"],
                region=row["region"] or _DEFAULT_REGION,
            )
        return tuple(seen.values())

    async def candidates(self, organization_id: UUID) -> tuple[ProviderDescriptor, ...]:
        return await self._descriptors(organization_id)

    async def get(self, organization_id: UUID, name: str) -> ProviderDescriptor | None:
        """Resolve one provider by name.

        Re-reads rather than filtering a cached ``candidates`` result: the engine calls this to
        confirm the runtime selected something the catalog really offers, and answering from a
        stale copy would defeat the integrity check it exists to perform.
        """
        for descriptor in await self._descriptors(organization_id):
            if descriptor.name == name:
                return descriptor
        return None
