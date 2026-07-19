"""MCP seam tests (ADR-0016 Slice 4).

Two questions: does the adapter map MCP onto ``ToolDescriptor`` correctly and safely, and does a
consumer written against the protocols work identically no matter which registry backend is
behind it.
"""

from __future__ import annotations

from typing import Any

import pytest

from gateway.adapters.mcp.fake_server import FakeMcpServer
from gateway.adapters.mcp.in_memory_gateway import InMemoryMcpGateway
from gateway.adapters.mcp.null_gateway import NullMcpGateway
from gateway.adapters.tools.in_memory_registry import InMemoryToolRegistry
from gateway.adapters.tools.static_manifest_registry import StaticManifestToolRegistry
from gateway.application.ports.mcp import McpInvocation
from gateway.application.tools.mcp_provisioner import McpToolProvisioner

ALL = frozenset({"tools:search", "tools:write"})


def make_server(**overrides: Any) -> FakeMcpServer:
    server = FakeMcpServer(
        name="acme",
        version="2.1.0",
        tools=[
            {
                "name": "search",
                "description": "Search the corpus.",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
            {"name": "write", "description": "Write a record."},
        ],
        handlers={
            "search": lambda args: {"hits": [args.get("q", "")]},
            "write": lambda args: {"written": True},
        },
    )
    for key, value in overrides.items():
        setattr(server, key, value)
    return server


def registries() -> list[Any]:
    return [InMemoryToolRegistry(), StaticManifestToolRegistry({"tools": []})]


# --------------------------------------------------------------------------- mapping


async def test_mcp_fields_map_onto_descriptor() -> None:
    gw = InMemoryMcpGateway(make_server())
    (search, write) = await gw.discover()
    assert search.name == "search"
    assert search.description == "Search the corpus."
    assert search.schema["properties"]["q"]["type"] == "string"
    # MCP declares no version; the server's version stands in for it.
    assert search.version == "2.1.0"
    assert search.qualified_name == "search@2.1.0"
    # Server-namespaced so discovery can select by origin.
    assert "mcp:acme" in search.capabilities
    # Absent optional fields default rather than crash.
    assert write.schema == {}


async def test_required_permissions_come_only_from_deployment_configuration() -> None:
    """The security property of the mapping: a server cannot declare its own authorization bar.

    The server here asserts, in every spelling it might plausibly use, that ``search`` needs
    nothing and that ``write`` grants itself an alarming permission. Both must be ignored: the
    only source is the operator-supplied mapping.
    """
    hostile = make_server(
        tools=[
            {"name": "search", "required_permissions": [], "permissions": []},
            {
                "name": "write",
                "required_permissions": ["tools:none"],
                "permissions": ["admin:all"],
                "requiredPermissions": ["admin:all"],
            },
        ]
    )
    gw = InMemoryMcpGateway(hostile, permissions={"search": ("tools:search",)})

    (search, write) = await gw.discover()
    # Operator config wins over the server's claim that nothing is required.
    assert search.required_permissions == ("tools:search",)
    # A server-declared permission is never adopted, in any spelling.
    assert write.required_permissions == ()
    assert "admin:all" not in write.required_permissions
    assert "tools:none" not in write.required_permissions

    # And the claim does not leak in through capabilities either.
    assert all("admin:all" not in cap for cap in write.capabilities)


async def test_server_cannot_escalate_by_being_configured_elsewhere() -> None:
    """Config is keyed by tool name, so a server renaming a tool loses its permissions."""
    gw = InMemoryMcpGateway(
        make_server(tools=[{"name": "search-v2"}]), permissions={"search": ("tools:search",)}
    )
    (tool,) = await gw.discover()
    assert tool.required_permissions == ()


# --------------------------------------------------------------------------- failure modes


async def test_malformed_entries_are_skipped_not_fatal() -> None:
    gw = InMemoryMcpGateway(make_server(malformed=True))
    assert await gw.discover() == ()


async def test_unreachable_server_discovers_nothing_and_reports_unhealthy() -> None:
    gw = InMemoryMcpGateway(make_server(reachable=False))
    assert await gw.discover() == ()
    health = await gw.health()
    assert health.healthy is False
    assert health.server == "acme"


async def test_timeout_is_returned_as_data_never_raised() -> None:
    gw = InMemoryMcpGateway(make_server(timeout=True))
    assert await gw.discover() == ()
    result = await gw.execute(McpInvocation(tool="search"))
    assert result.ok is False
    assert "timed out" in (result.error or "")


async def test_unknown_tool_at_the_gateway_fails_closed() -> None:
    gw = InMemoryMcpGateway(make_server())
    result = await gw.execute(McpInvocation(tool="nope"))
    assert result.ok is False
    assert result.content is None


async def test_healthy_server_reports_healthy() -> None:
    assert (await InMemoryMcpGateway(make_server()).health()).healthy is True


# --------------------------------------------------------------------------- consumer parity


@pytest.mark.parametrize("registry", registries(), ids=["in_memory", "static_manifest"])
async def test_discover_register_resolve_invoke(registry: Any) -> None:
    gw = InMemoryMcpGateway(make_server(), permissions={"search": ("tools:search",)})
    provisioner = McpToolProvisioner(gw, registry)

    discovered = await provisioner.sync()
    assert {d.name for d in discovered} == {"search", "write"}

    # Registered, therefore resolvable through the registry - not through the gateway.
    assert await registry.get("search") is not None

    result = await provisioner.invoke("search", {"q": "acme"}, ALL)
    assert result.ok is True
    assert result.content == {"hits": ["acme"]}


@pytest.mark.parametrize("registry", registries(), ids=["in_memory", "static_manifest"])
async def test_capabilities_propagate_through_registration(registry: Any) -> None:
    provisioner = McpToolProvisioner(InMemoryMcpGateway(make_server()), registry)
    await provisioner.sync()
    found = await registry.discover(capabilities=("mcp:acme",))
    assert {d.name for d in found} == {"search", "write"}


@pytest.mark.parametrize("registry", registries(), ids=["in_memory", "static_manifest"])
async def test_invoking_an_unregistered_tool_fails_closed(registry: Any) -> None:
    provisioner = McpToolProvisioner(InMemoryMcpGateway(make_server()), registry)
    result = await provisioner.invoke("search", {}, ALL)  # no sync() first
    assert result.ok is False
    assert "unknown tool" in (result.error or "")


@pytest.mark.parametrize("registry", registries(), ids=["in_memory", "static_manifest"])
async def test_missing_permission_denies_without_reaching_the_server(registry: Any) -> None:
    server = make_server()
    gw = InMemoryMcpGateway(server, permissions={"search": ("tools:search",)})
    provisioner = McpToolProvisioner(gw, registry)
    await provisioner.sync()
    server.reachable = False  # if this were reached, the error would say "unreachable"

    result = await provisioner.invoke("search", {}, frozenset())
    assert result.ok is False
    assert "permission denied" in (result.error or "")
    # The denial must not name the permission the caller is missing.
    assert "tools:search" not in (result.error or "")


@pytest.mark.parametrize("registry", registries(), ids=["in_memory", "static_manifest"])
async def test_outage_does_not_deregister_known_tools(registry: Any) -> None:
    server = make_server()
    provisioner = McpToolProvisioner(InMemoryMcpGateway(server), registry)
    await provisioner.sync()
    server.reachable = False
    assert await provisioner.sync() == ()
    assert await registry.get("search") is not None


@pytest.mark.parametrize("registry", registries(), ids=["in_memory", "static_manifest"])
async def test_null_gateway_is_protocol_compatible(registry: Any) -> None:
    """Rule 4 - the null implementation satisfies the same consumer without special-casing."""
    provisioner = McpToolProvisioner(NullMcpGateway(), registry)
    assert await provisioner.sync() == ()
    result = await provisioner.invoke("search", {}, ALL)
    assert result.ok is False
