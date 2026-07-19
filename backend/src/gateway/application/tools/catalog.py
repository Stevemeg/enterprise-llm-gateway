"""ToolCatalog - the first genuine consumer of the ToolRegistry seam (ADR-0016 invariant 2).

Deliberately small: its job is to prove the seam, not to add behaviour. It exercises every
protocol method and is constructed with a ``ToolRegistry``, so it cannot know - and must never
learn - which backend is behind it.

``available_for`` is the one method that combines two protocol calls, and it is the reason this
consumer exists: discovery and permission filtering belong together at the call site, because a
caller that discovers without filtering has a list of tools it may not use.
"""

from __future__ import annotations

from uuid import UUID

from gateway.application.ports.tools import ToolDescriptor, ToolRegistry


class ToolCatalog:
    """Read/write facade over a registry, filtered by the caller's permissions."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def publish(self, descriptor: ToolDescriptor) -> None:
        """Make a tool available. Re-publishing the same qualified name replaces it."""
        await self._registry.register(descriptor)

    async def resolve(self, name: str, version: str | None = None) -> ToolDescriptor | None:
        """Resolve one tool. ``None`` when absent so callers fail closed."""
        return await self._registry.get(name, version)

    async def available_for(
        self,
        granted_permissions: frozenset[str],
        *,
        capabilities: tuple[str, ...] = (),
        organization_id: UUID | None = None,
    ) -> tuple[ToolDescriptor, ...]:
        """Tools matching every requested capability **and** permitted to this caller.

        Filtering happens here rather than in the caller so a discovery result is never a list of
        tools the holder cannot actually invoke.
        """
        discovered = await self._registry.discover(
            capabilities=capabilities, organization_id=organization_id
        )
        permitted: list[ToolDescriptor] = []
        for descriptor in discovered:
            if await self._registry.permitted(descriptor, granted_permissions):
                permitted.append(descriptor)
        return tuple(permitted)

    async def can_use(
        self, name: str, granted_permissions: frozenset[str], version: str | None = None
    ) -> bool:
        """Whether a specific tool exists **and** is permitted. Unknown tool ⇒ False."""
        descriptor = await self._registry.get(name, version)
        if descriptor is None:
            return False
        return await self._registry.permitted(descriptor, granted_permissions)
