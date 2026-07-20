"""Grants nothing to anyone (ADR-0016 Rule 4).

The safe default and the proof that the port is implementable before storage exists. It is also
the resolver a misconfigured deployment gets, which is why it grants rather than denies by
returning an empty set: an unwired RBAC subsystem must deny every request, not allow every one.
"""

from __future__ import annotations

from uuid import UUID

from gateway.application.ports.authorization import PermissionResolver


class NullPermissionResolver(PermissionResolver):
    """Always resolves to no permissions."""

    async def resolve(self, principal_id: UUID, organization_id: UUID) -> frozenset[str]:
        return frozenset()
