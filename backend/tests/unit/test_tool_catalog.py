"""ToolCatalog - first consumer of the ToolRegistry seam.

Every test runs against **both** backends. The consumer is constructed with a protocol and must
behave identically regardless of which implementation is injected - that is the seam working.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from gateway.adapters.tools.in_memory_registry import InMemoryToolRegistry
from gateway.adapters.tools.static_manifest_registry import StaticManifestToolRegistry
from gateway.application.ports.tools import ToolDescriptor, ToolRegistry
from gateway.application.tools.catalog import ToolCatalog

RegistryFactory = Callable[[], ToolRegistry]
FACTORIES: list[RegistryFactory] = [
    InMemoryToolRegistry,
    lambda: StaticManifestToolRegistry({"tools": []}),
]
IDS = ["in_memory", "static_manifest"]


@pytest.fixture(params=FACTORIES, ids=IDS)
def catalog(request: pytest.FixtureRequest) -> ToolCatalog:
    factory: RegistryFactory = request.param
    return ToolCatalog(factory())


def _tool(name: str, version: str = "1.0.0", **kwargs: object) -> ToolDescriptor:
    return ToolDescriptor(name=name, version=version, description="t", **kwargs)  # type: ignore[arg-type]


async def test_publish_then_resolve(catalog: ToolCatalog) -> None:
    await catalog.publish(_tool("github"))
    found = await catalog.resolve("github")
    assert found is not None
    assert found.qualified_name == "github@1.0.0"


async def test_resolve_unknown_tool_returns_none(catalog: ToolCatalog) -> None:
    assert await catalog.resolve("nope") is None


async def test_resolve_honours_explicit_version(catalog: ToolCatalog) -> None:
    await catalog.publish(_tool("github", "1.0.0"))
    await catalog.publish(_tool("github", "2.0.0"))
    pinned = await catalog.resolve("github", "1.0.0")
    assert pinned is not None
    assert pinned.version == "1.0.0"


async def test_available_for_filters_out_tools_the_caller_cannot_use(
    catalog: ToolCatalog,
) -> None:
    """Discovery must never hand back tools the holder lacks permission to invoke."""
    await catalog.publish(
        _tool("github", capabilities=("search",), required_permissions=("tool:github",))
    )
    await catalog.publish(
        _tool("slack", capabilities=("search",), required_permissions=("tool:slack",))
    )

    visible = await catalog.available_for(frozenset({"tool:github"}), capabilities=("search",))

    assert [d.name for d in visible] == ["github"]


async def test_available_for_returns_nothing_without_permissions(catalog: ToolCatalog) -> None:
    await catalog.publish(_tool("github", required_permissions=("tool:github",)))
    assert await catalog.available_for(frozenset()) == ()


async def test_available_for_includes_tools_requiring_no_permission(
    catalog: ToolCatalog,
) -> None:
    await catalog.publish(_tool("open"))
    assert [d.name for d in await catalog.available_for(frozenset())] == ["open"]


async def test_available_for_requires_every_capability(catalog: ToolCatalog) -> None:
    await catalog.publish(_tool("github", capabilities=("search", "issues")))
    await catalog.publish(_tool("slack", capabilities=("search",)))
    both = await catalog.available_for(frozenset(), capabilities=("search", "issues"))
    assert [d.name for d in both] == ["github"]


async def test_can_use_is_false_for_unknown_tool(catalog: ToolCatalog) -> None:
    assert await catalog.can_use("nope", frozenset()) is False


async def test_can_use_fails_closed_on_missing_permission(catalog: ToolCatalog) -> None:
    await catalog.publish(_tool("github", required_permissions=("tool:github", "repo:read")))
    assert await catalog.can_use("github", frozenset({"tool:github"})) is False
    assert await catalog.can_use("github", frozenset({"tool:github", "repo:read"})) is True


async def test_catalog_behaviour_is_identical_across_backends() -> None:
    """The same script against both backends must produce the same observable result."""
    results = []
    for factory in FACTORIES:
        catalog = ToolCatalog(factory())
        await catalog.publish(_tool("github", "1.0.0", capabilities=("search",)))
        await catalog.publish(_tool("github", "2.0.0", capabilities=("search",)))
        newest = await catalog.resolve("github")
        visible = await catalog.available_for(frozenset(), capabilities=("search",))
        results.append((newest.version if newest else None, len(visible)))
    assert results[0] == results[1], f"backends diverged: {results}"
