"""Manifest-backed ToolRegistry - the second implementation (ADR-0016 Rule 4).

Its purpose is experimental as much as functional: if a second backend can satisfy
``ToolRegistry`` with **no protocol change**, Rule 4's claim (one implementation is enough to
prove a seam) holds. If it cannot, Rule 5 is triggered and the milestone stops.

Loads ``ToolDescriptor`` objects from a declarative manifest - the shape a self-hosted deployment
would ship as configuration. Storage differs from ``InMemoryToolRegistry`` (seeded and immutable
at construction vs. empty and populated at runtime); observable behaviour must not.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from gateway.application.ports.tools import ToolDescriptor, ToolRegistry


class ManifestError(ValueError):
    """The manifest could not be parsed. Fail at load time, never at lookup time."""


def _descriptor_from_entry(entry: dict[str, Any], index: int) -> ToolDescriptor:
    try:
        name = str(entry["name"])
        version = str(entry["version"])
    except KeyError as exc:  # a tool without identity is unusable - reject the whole manifest
        raise ManifestError(f"manifest entry {index} is missing {exc.args[0]!r}") from exc
    return ToolDescriptor(
        name=name,
        version=version,
        description=str(entry.get("description", "")),
        capabilities=tuple(entry.get("capabilities", ())),
        required_permissions=tuple(entry.get("required_permissions", ())),
        schema=dict(entry.get("schema", {})),
    )


class StaticManifestToolRegistry(ToolRegistry):
    """A registry seeded from a manifest.

    ``register`` remains supported: the manifest is the *initial* set, not a permanent ceiling.
    Refusing registration would have made this implementation a partial one, which is exactly the
    kind of divergence the parity tests exist to catch.
    """

    def __init__(self, manifest: dict[str, Any] | None = None) -> None:
        self._tools: dict[str, ToolDescriptor] = {}
        entries = (manifest or {}).get("tools", [])
        if not isinstance(entries, list):
            raise ManifestError("manifest 'tools' must be a list")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ManifestError(f"manifest entry {index} must be an object")
            descriptor = _descriptor_from_entry(entry, index)
            self._tools[descriptor.qualified_name] = descriptor

    async def register(self, descriptor: ToolDescriptor) -> None:
        self._tools[descriptor.qualified_name] = descriptor

    async def get(self, name: str, version: str | None = None) -> ToolDescriptor | None:
        if version is not None:
            return self._tools.get(f"{name}@{version}")
        matches = [d for d in self._tools.values() if d.name == name]
        return max(matches, key=lambda d: d.version) if matches else None

    async def discover(
        self,
        *,
        capabilities: tuple[str, ...] = (),
        organization_id: UUID | None = None,
    ) -> tuple[ToolDescriptor, ...]:
        wanted = set(capabilities)
        return tuple(d for d in self._tools.values() if wanted.issubset(set(d.capabilities)))

    async def permitted(
        self, descriptor: ToolDescriptor, granted_permissions: frozenset[str]
    ) -> bool:
        return set(descriptor.required_permissions).issubset(granted_permissions)
