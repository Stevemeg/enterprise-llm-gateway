"""In-memory role-to-permission resolver (ADR-0016 Rule 4, second implementation).

Roles are indirection between principals and permissions: principals hold roles, roles carry
permissions, and the resolver flattens the two. Keeping the flattening here rather than in the
stage means the stage never learns that roles exist, so a future database-backed resolver that
computes permissions by an entirely different route substitutes without touching enforcement.

Assignments are keyed by ``(organization_id, principal_id)``. The organization is part of the
identity of a grant, not a filter applied afterwards - a principal who holds ``admin`` in one
tenant must resolve to nothing in another, and making the tenant part of the key means that
property cannot be lost by forgetting a comparison.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID

from gateway.application.ports.authorization import PermissionResolver


class InMemoryPermissionResolver(PermissionResolver):
    """Resolves permissions from static role assignments."""

    def __init__(
        self,
        role_permissions: Mapping[str, Iterable[str]] | None = None,
        assignments: Mapping[tuple[UUID, UUID], Iterable[str]] | None = None,
    ) -> None:
        self._role_permissions = {
            role: frozenset(perms) for role, perms in (role_permissions or {}).items()
        }
        self._assignments = {key: tuple(roles) for key, roles in (assignments or {}).items()}

    def assign(self, organization_id: UUID, principal_id: UUID, roles: Iterable[str]) -> None:
        """Grant roles to a principal within one organization. Replaces any prior assignment."""
        self._assignments[(organization_id, principal_id)] = tuple(roles)

    async def resolve(self, principal_id: UUID, organization_id: UUID) -> frozenset[str]:
        roles = self._assignments.get((organization_id, principal_id), ())
        granted: set[str] = set()
        for role in roles:
            # An unknown role contributes nothing rather than raising: role definitions and role
            # assignments can be edited independently, so a dangling assignment is expected and
            # must narrow authority, never widen it or break the request.
            granted |= self._role_permissions.get(role, frozenset())
        return frozenset(granted)
