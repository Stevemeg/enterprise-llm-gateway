"""Minimal ToolRegistry implementation (ADR-0016 Rule 4).

In-memory, single-process. Validates the port and backs tests; a durable registry arrives with
the MCP milestone.
"""

from __future__ import annotations

from uuid import UUID

from gateway.application.ports.tools import ToolDescriptor, ToolRegistry


class InMemoryToolRegistry(ToolRegistry):
    def __init__(self) -> None:
        self._tools: dict[str, ToolDescriptor] = {}

    async def register(self, descriptor: ToolDescriptor) -> None:
        self._tools[descriptor.qualified_name] = descriptor

    async def get(self, name: str, version: str | None = None) -> ToolDescriptor | None:
        if version is not None:
            return self._tools.get(f"{name}@{version}")
        matches = [d for d in self._tools.values() if d.name == name]
        # Unversioned lookup returns the newest registered version, deterministically.
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
        # Fail closed: every required permission must be present.
        return set(descriptor.required_permissions).issubset(granted_permissions)
