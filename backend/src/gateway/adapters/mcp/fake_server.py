"""In-memory MCP server simulation (ADR-0016 Slice 4).

Stands in for a real MCP server so protocol compatibility can be proven without networking,
authentication or retries - none of which are the question this milestone asks. It mimics the
shape of an MCP server's responses, including the parts that make MCP *awkward*: tools carry a
name, description and input schema, but **no version, no capability list and no permissions**.

Those absences are the interesting part. If the adapter can supply them without the protocol
changing, Rule 1 holds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class McpTransportError(RuntimeError):
    """The simulated server was unreachable or returned something unusable."""


@dataclass
class FakeMcpServer:
    """A scriptable MCP server. ``tools`` mirrors an MCP ``tools/list`` response."""

    name: str = "fake"
    version: str = "1.0.0"
    tools: list[dict[str, Any]] = field(default_factory=list)
    handlers: dict[str, Callable[[dict[str, Any]], Any]] = field(default_factory=dict)
    reachable: bool = True
    malformed: bool = False
    timeout: bool = False

    def list_tools(self) -> list[dict[str, Any]]:
        if self.timeout:
            raise TimeoutError("simulated MCP timeout")
        if not self.reachable:
            raise McpTransportError("simulated MCP server unreachable")
        if self.malformed:
            return [{"unexpected": "shape"}]  # no 'name' - must be rejected, not crash
        return list(self.tools)

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> Any:
        if self.timeout:
            raise TimeoutError("simulated MCP timeout")
        if not self.reachable:
            raise McpTransportError("simulated MCP server unreachable")
        handler = self.handlers.get(tool)
        if handler is None:
            raise McpTransportError(f"unknown tool {tool!r}")
        return handler(arguments)
