"""RBAC authorization seam (ADR-0016 Slice 5) - an **RBAC-owned application port**, not Tier-1.

Tier-1 protocols are frozen and RBAC needed none of them changed (Rule 5 not triggered). What it
did need is a way to answer "what may this principal do", which no existing protocol answers, so
the capability introduces its own port rather than widening a shared one. That is the distinction
Rule 1 turns on: a concern every consumer shares belongs in Tier 1, a concern one capability owns
belongs to that capability.

Resolution returns a set rather than raising on an unknown principal. An unknown principal is an
ordinary outcome - a deleted user, a stale token, a principal from another tenant - and a caller
forced to catch an exception to discover it will eventually forget to. The empty set it receives
instead denies everything, so forgetting fails closed.

Protocol only. No storage, no roles table (Rule 2).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class PermissionResolver(Protocol):
    """Resolves the permissions currently granted to a principal within one organization."""

    async def resolve(self, principal_id: UUID, organization_id: UUID) -> frozenset[str]:
        """Permissions granted to this principal **in this organization**.

        Scoped by organization because the same principal may hold different roles in different
        tenants, and a resolver that ignored the organization would leak authority across the
        isolation boundary that RLS enforces at the storage layer.

        Unknown principal, unknown organization, or a principal with no roles all return the
        empty set. Never raises.
        """
        ...
