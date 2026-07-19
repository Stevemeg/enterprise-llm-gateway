"""MCP gateway seam (ADR-0016, Tier-1 invariant 1).

Every executable capability must be representable as an MCP tool. Defining this port now means
MCP servers (GitHub, PostgreSQL, Slack, filesystem, browser) arrive later as adapters rather than
as a change to execution interfaces.

Protocol only. No MCP client, no server, no networking (Rule 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from gateway.application.ports.tools import ToolDescriptor


@dataclass(frozen=True, slots=True)
class McpInvocation:
    """A request to execute a tool. ``correlation_id`` ties it to the originating request."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""


@dataclass(frozen=True, slots=True)
class McpResult:
    """Outcome of an invocation. Failure is data, not an exception, so callers must handle it."""

    ok: bool
    content: Any = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class McpHealth:
    """Reachability of an MCP server, for routing and circuit-breaking."""

    healthy: bool
    server: str = ""
    detail: str | None = None


class McpGateway(Protocol):
    """Executes tools over the Model Context Protocol."""

    async def discover(self) -> tuple[ToolDescriptor, ...]:
        """Tools this gateway can execute, in registry terms."""
        ...

    async def execute(self, invocation: McpInvocation) -> McpResult:
        """Run a tool. Must not raise for tool-level failure - return ``ok=False``."""
        ...

    async def health(self) -> McpHealth: ...
