"""McpGateway backed by a simulated MCP server (ADR-0016 Slice 4, Rule 4).

**The experiment.** MCP is an external specification we do not control. If it can be expressed
through the existing ``McpGateway`` and ``ToolDescriptor`` without either changing, Rule 1's
counterfactual admission test held; if not, Rule 5 is triggered.

## MCP -> ToolDescriptor mapping

MCP describes a tool with three fields. ``ToolDescriptor`` has six. The three it does not
describe are supplied here, by the adapter, from deployment-local knowledge - which is what an
adapter is for. The protocol is not deficient; the external specification is narrower.

* ``name`` <- MCP ``name``, verbatim. An entry without one is skipped, not guessed.
* ``description`` <- MCP ``description``, verbatim, defaulting to ``""``.
* ``schema`` <- MCP ``inputSchema``, verbatim, defaulting to ``{}``.
* ``version`` <- the **server's** version. A tool that declares no version of its own is
  versioned by its provider, so ``search@2.1.0`` reads as "search, as exposed by server 2.1.0".
* ``capabilities`` <- ``mcp:<server>`` plus anything the tool declares, so discovery can select
  by origin without the registry knowing MCP exists.
* ``required_permissions`` <- **deployment configuration only**, never the server.

### Why permissions can never come from MCP metadata

The first three rows are transcription and the next two are defaulting, but
``required_permissions`` is a security decision. A permission requirement is an assertion the
*operator* makes about a tool: "invoking this costs money" or "this reads customer data". If the
adapter accepted it from the server, a remote party would be declaring its own authorization bar
and could lower it to nothing simply by omitting the field.

So server-supplied permission metadata is not merely ignored by omission - it is never read. The
only source is the ``permissions`` mapping passed at construction, and an unconfigured tool gets
``()``, which under ``ToolRegistry.permitted`` means "no permission required". That default is
deliberate and it is the reason this must be operator-configured: an unconfigured MCP tool is
open, so the safety of the deployment rests on the operator declaring requirements, not on the
adapter inferring them from an untrusted source.
"""

from __future__ import annotations

from typing import Any

from gateway.adapters.mcp.fake_server import FakeMcpServer, McpTransportError
from gateway.application.ports.mcp import McpGateway, McpHealth, McpInvocation, McpResult
from gateway.application.ports.tools import ToolDescriptor

MCP_CAPABILITY_PREFIX = "mcp"


class InMemoryMcpGateway(McpGateway):
    """Speaks to a ``FakeMcpServer``; satisfies ``McpGateway`` unchanged."""

    def __init__(
        self,
        server: FakeMcpServer,
        *,
        permissions: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._server = server
        # Operator-declared, never server-declared.
        self._permissions = dict(permissions or {})

    def _to_descriptor(self, entry: dict[str, Any]) -> ToolDescriptor | None:
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            return None  # malformed entry: skip it rather than fail the whole discovery
        declared = tuple(entry.get("capabilities", ()))
        return ToolDescriptor(
            name=name,
            version=self._server.version,
            description=str(entry.get("description", "")),
            capabilities=(f"{MCP_CAPABILITY_PREFIX}:{self._server.name}", *declared),
            required_permissions=self._permissions.get(name, ()),
            schema=dict(entry.get("inputSchema", {})),
        )

    async def discover(self) -> tuple[ToolDescriptor, ...]:
        try:
            entries = self._server.list_tools()
        except (TimeoutError, McpTransportError):
            # Fail closed: an unreachable server advertises nothing rather than raising into
            # the caller's discovery path.
            return ()
        descriptors = [self._to_descriptor(entry) for entry in entries]
        return tuple(d for d in descriptors if d is not None)

    async def execute(self, invocation: McpInvocation) -> McpResult:
        try:
            content = self._server.call_tool(invocation.tool, dict(invocation.arguments))
        except TimeoutError:
            return McpResult(ok=False, error="mcp invocation timed out")
        except McpTransportError as exc:
            return McpResult(ok=False, error=str(exc))
        return McpResult(ok=True, content=content)

    async def health(self) -> McpHealth:
        try:
            self._server.list_tools()
        except (TimeoutError, McpTransportError) as exc:
            return McpHealth(healthy=False, server=self._server.name, detail=str(exc))
        return McpHealth(healthy=True, server=self._server.name)
