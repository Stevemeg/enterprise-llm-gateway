"""Minimal McpGateway implementation (ADR-0016 Rule 4).

Advertises nothing and executes nothing, reporting failure as data rather than raising. Proves
the port is implementable without introducing a client, a server or any networking.
"""

from __future__ import annotations

from gateway.application.ports.mcp import McpGateway, McpHealth, McpInvocation, McpResult
from gateway.application.ports.tools import ToolDescriptor


class NullMcpGateway(McpGateway):
    async def discover(self) -> tuple[ToolDescriptor, ...]:
        return ()

    async def execute(self, invocation: McpInvocation) -> McpResult:
        return McpResult(ok=False, error=f"no MCP server configured for tool {invocation.tool!r}")

    async def health(self) -> McpHealth:
        return McpHealth(healthy=False, server="null", detail="no MCP gateway configured")
