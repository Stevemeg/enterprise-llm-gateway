"""McpToolProvisioner - the first consumer of the MCP seam (ADR-0016 Slice 4).

Depends on ``McpGateway`` and ``ToolRegistry`` and on nothing else. It never learns which MCP
transport is behind the gateway or which backend is behind the registry, which is the whole point:
if this class could be written without either protocol changing, an external specification was
absorbed by the existing seams.

It closes the loop the slice is about - **discover -> register -> resolve -> invoke -> result** -
and it is the reason the two seams have to meet somewhere. Discovery yields descriptors, the
registry is what makes them findable later, and invocation must go back through the gateway. No
single protocol spans that, so a consumer must.

Every failure is returned as ``McpResult(ok=False, ...)`` rather than raised. Unknown tools and
denied permissions are ordinary outcomes of a routing decision, not exceptional control flow, and
a caller that has to catch exceptions to discover it lacks permission will eventually forget to.
"""

from __future__ import annotations

from typing import Any

from gateway.application.ports.mcp import McpGateway, McpInvocation, McpResult
from gateway.application.ports.tools import ToolDescriptor, ToolRegistry


class McpToolProvisioner:
    """Publishes MCP-discovered tools into the registry and invokes them back through MCP."""

    def __init__(self, gateway: McpGateway, registry: ToolRegistry) -> None:
        self._gateway = gateway
        self._registry = registry

    async def sync(self) -> tuple[ToolDescriptor, ...]:
        """Discover from MCP and register everything found.

        An unreachable server discovers nothing, so this registers nothing and returns ``()``.
        It does not deregister previously known tools: a transient outage must not silently strip
        a tenant's toolset, and removal is a decision no single discovery round can justify.
        """
        descriptors = await self._gateway.discover()
        for descriptor in descriptors:
            await self._registry.register(descriptor)
        return descriptors

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any],
        granted_permissions: frozenset[str],
        *,
        version: str | None = None,
        correlation_id: str = "",
    ) -> McpResult:
        """Resolve through the registry, then execute through the gateway.

        Resolution happens against the *registry*, not the gateway, so a tool must have been
        published before it can be invoked. That ordering is what makes permission enforcement
        possible at all - the gateway knows how to call a tool but nothing about who may.
        """
        descriptor = await self._registry.get(name, version)
        if descriptor is None:
            return McpResult(ok=False, error=f"unknown tool: {name}")
        if not await self._registry.permitted(descriptor, granted_permissions):
            # Fail closed, and say only that it was denied - naming the missing permission tells
            # an unauthorized caller what to go acquire.
            return McpResult(ok=False, error=f"permission denied: {descriptor.qualified_name}")
        return await self._gateway.execute(
            McpInvocation(
                tool=descriptor.name, arguments=dict(arguments), correlation_id=correlation_id
            )
        )
