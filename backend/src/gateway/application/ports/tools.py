"""Tool Registry seam (ADR-0016, Tier-1 invariant 2).

Nothing discovers or constructs a tool except through this registry. Hard-coding a tool client
anywhere else defeats capability discovery, versioning and permission enforcement in one step -
and does so silently, which is why it is CI-enforced rather than left to review.

Protocol only. No tools, no MCP (Rule 2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """What a tool advertises about itself.

    ``required_permissions`` is declared here rather than checked at the call site so that
    authorization can be enforced uniformly by the registry once RBAC exists.
    """

    name: str
    version: str
    description: str
    capabilities: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    schema: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        """``name@version`` - tools are versioned, so identity includes the version."""
        return f"{self.name}@{self.version}"


class ToolRegistry(Protocol):
    """Registration, lookup, discovery and permission filtering for executable tools."""

    async def register(self, descriptor: ToolDescriptor) -> None:
        """Add or replace a tool. Re-registering the same qualified name replaces it."""
        ...

    async def get(self, name: str, version: str | None = None) -> ToolDescriptor | None:
        """Resolve one tool; ``None`` when absent so callers fail closed."""
        ...

    async def discover(
        self,
        *,
        capabilities: tuple[str, ...] = (),
        organization_id: UUID | None = None,
    ) -> tuple[ToolDescriptor, ...]:
        """List tools matching every requested capability."""
        ...

    async def permitted(
        self, descriptor: ToolDescriptor, granted_permissions: frozenset[str]
    ) -> bool:
        """Whether the holder of ``granted_permissions`` may use this tool."""
        ...
