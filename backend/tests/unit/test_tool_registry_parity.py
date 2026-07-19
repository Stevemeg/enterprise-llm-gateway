"""Registry parity - the Tool Registry milestone's central experiment (ADR-0016 Rules 4, 5).

The question this milestone exists to answer: **can ToolRegistry support multiple implementations
with no protocol change?**

Every behavioural test below runs against *both* backends via parametrisation. Two
implementations with different storage models (empty-and-populated vs. manifest-seeded) must be
observably identical through the protocol. A divergence here is not a test failure - it is
evidence that the protocol under-specifies behaviour, which triggers Rule 5.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from gateway.adapters.tools.in_memory_registry import InMemoryToolRegistry
from gateway.adapters.tools.static_manifest_registry import (
    ManifestError,
    StaticManifestToolRegistry,
)
from gateway.application.ports.tools import ToolDescriptor, ToolRegistry

RegistryFactory = Callable[[], ToolRegistry]

# Both factories start EMPTY so parity tests compare behaviour, not seed data.
FACTORIES: list[RegistryFactory] = [
    InMemoryToolRegistry,
    lambda: StaticManifestToolRegistry({"tools": []}),
]
IDS = ["in_memory", "static_manifest"]


@pytest.fixture(params=FACTORIES, ids=IDS)
def registry(request: pytest.FixtureRequest) -> ToolRegistry:
    factory: RegistryFactory = request.param
    return factory()


def _tool(name: str, version: str, **kwargs: object) -> ToolDescriptor:
    return ToolDescriptor(name=name, version=version, description="t", **kwargs)  # type: ignore[arg-type]


# --- protocol conformance -------------------------------------------------------------------


@pytest.mark.parametrize("factory", FACTORIES, ids=IDS)
def test_every_backend_satisfies_the_protocol(factory: RegistryFactory) -> None:
    instance = factory()
    for method in ("register", "get", "discover", "permitted"):
        assert hasattr(instance, method), f"{type(instance).__name__} missing {method}"


# --- behavioural parity ---------------------------------------------------------------------


async def test_registration_then_explicit_version_lookup(registry: ToolRegistry) -> None:
    await registry.register(_tool("github", "1.0.0"))
    found = await registry.get("github", "1.0.0")
    assert found is not None
    assert found.qualified_name == "github@1.0.0"


async def test_unversioned_lookup_returns_newest(registry: ToolRegistry) -> None:
    await registry.register(_tool("github", "1.0.0"))
    await registry.register(_tool("github", "2.0.0"))
    newest = await registry.get("github")
    assert newest is not None
    assert newest.version == "2.0.0"


async def test_duplicate_registration_replaces(registry: ToolRegistry) -> None:
    await registry.register(_tool("github", "1.0.0", capabilities=("search",)))
    await registry.register(_tool("github", "1.0.0", capabilities=("search", "issues")))
    found = await registry.get("github", "1.0.0")
    assert found is not None
    assert found.capabilities == ("search", "issues")
    assert len(await registry.discover()) == 1, "replacement must not duplicate the entry"


async def test_unknown_tool_returns_none(registry: ToolRegistry) -> None:
    assert await registry.get("nope") is None
    assert await registry.get("nope", "1.0.0") is None


async def test_capability_discovery_requires_every_capability(registry: ToolRegistry) -> None:
    await registry.register(_tool("github", "1.0.0", capabilities=("search", "issues")))
    await registry.register(_tool("slack", "1.0.0", capabilities=("search",)))
    assert len(await registry.discover()) == 2
    assert len(await registry.discover(capabilities=("search",))) == 2
    assert [d.name for d in await registry.discover(capabilities=("search", "issues"))] == [
        "github"
    ]


async def test_unknown_capability_yields_nothing(registry: ToolRegistry) -> None:
    await registry.register(_tool("github", "1.0.0", capabilities=("search",)))
    assert await registry.discover(capabilities=("teleport",)) == ()


async def test_permission_check_fails_closed(registry: ToolRegistry) -> None:
    tool = _tool("github", "1.0.0", required_permissions=("tool:github", "repo:read"))
    assert await registry.permitted(tool, frozenset()) is False
    assert await registry.permitted(tool, frozenset({"tool:github"})) is False
    assert await registry.permitted(tool, frozenset({"tool:github", "repo:read"})) is True


async def test_tool_requiring_nothing_is_permitted(registry: ToolRegistry) -> None:
    assert await registry.permitted(_tool("open", "1.0.0"), frozenset()) is True


async def test_empty_registry_discovers_nothing(registry: ToolRegistry) -> None:
    assert await registry.discover() == ()


# --- manifest-specific loading (not parity - construction differs by design) -------------------


async def test_manifest_seeds_tools_at_construction() -> None:
    registry = StaticManifestToolRegistry(
        {
            "tools": [
                {
                    "name": "github",
                    "version": "1.0.0",
                    "description": "GitHub",
                    "capabilities": ["search"],
                    "required_permissions": ["tool:github"],
                }
            ]
        }
    )
    found = await registry.get("github")
    assert found is not None
    assert found.capabilities == ("search",)
    assert await registry.permitted(found, frozenset()) is False


async def test_manifest_seeded_registry_still_accepts_registration() -> None:
    """A seeded registry is not read-only; refusing register() would be partial conformance."""
    registry = StaticManifestToolRegistry({"tools": [{"name": "github", "version": "1.0.0"}]})
    await registry.register(_tool("slack", "1.0.0"))
    assert len(await registry.discover()) == 2


@pytest.mark.parametrize(
    "manifest",
    [
        {"tools": [{"version": "1.0.0"}]},
        {"tools": [{"name": "github"}]},
        {"tools": ["not-an-object"]},
        {"tools": "not-a-list"},
    ],
)
def test_malformed_manifest_fails_at_load_not_at_lookup(manifest: dict[str, object]) -> None:
    """Fail closed at construction - a half-loaded registry would silently lose tools."""
    with pytest.raises(ManifestError):
        StaticManifestToolRegistry(manifest)


def test_missing_manifest_yields_an_empty_registry() -> None:
    assert StaticManifestToolRegistry() is not None
