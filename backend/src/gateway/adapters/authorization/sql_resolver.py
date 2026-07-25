"""Durable, tenant-scoped ``PermissionResolver`` backed by PostgreSQL (ADR-0008, Slice 18).

The third implementation of the Slice-5 port, and the first with real storage. Substituting it for
``NullPermissionResolver`` changes one line in the composition root and nothing else - which is the
property the port was introduced to buy, now actually collected.

## Two principal shapes, one question

ADR-0008 defines two kinds of principal and gives them authority by different routes:

* **users and service accounts** hold *roles*: ``membership -> role -> role_permission ->
  permission``;
* **virtual API keys** hold *scopes* directly (``api_key_scope``), a deliberately constrained
  inference-only subset - "keys never carry admin permissions".

Both are answers to the same question the port asks, so both are resolved here and unioned. No
principal *type* parameter is needed (and so the port is unchanged - Rule 5 not triggered): the two
branches key on ``api_key.id`` and ``app_user.id``/``service_account.id`` respectively, which are
distinct UUIDs, so a principal matches at most one branch by construction.

## Where tenant isolation actually comes from

Every query runs inside ``AsyncUnitOfWork(tenant_id=organization_id)``, so RLS filters
``membership`` and ``api_key_scope`` - both tenant-scoped tables - to this organization. That is
the real boundary. ``role``, ``role_permission`` and ``permission`` carry no RLS *by design*
(``role.organization_id`` is nullable: NULL means a global system role), so they are traversed only
from an already-tenant-filtered ``membership`` row and are never enumerated.

Two predicates are then belt-and-braces on top of that, and both are load-bearing rather than
decorative:

* ``role.organization_id IS NULL OR = :org`` - no composite foreign key stops a ``membership`` row
  in one tenant from pointing at another tenant's custom role, and RLS on ``membership`` would not
  notice, because the offending column is on ``role``.
* ``membership.status = 'active'`` - ``invited`` has not accepted and ``disabled`` has been
  switched off. Either granting anything would be a silent privilege leak.

## Failure is denial, and it is never silent

The port's contract is "never raises", which makes a database outage resolve to the empty set and
therefore deny (ADR-0009 rows 6 and 15 - authorization and Postgres both fail closed). Swallowing
the error without a trace would turn an outage into a mysterious wave of 403s, so it is logged at
error level with the exception *type* only - never its message, which can quote query parameters.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, union
from sqlalchemy.exc import SQLAlchemyError

from gateway.adapters.persistence.rbac_tables import (
    ACTIVE_MEMBERSHIP,
    membership,
    permission,
    role,
    role_permission,
)
from gateway.adapters.persistence.tables import api_key_scope
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.ports.authorization import PermissionResolver
from gateway.observability.logging import get_logger

_logger = get_logger("authorization")


class SqlPermissionResolver(PermissionResolver):
    """Resolves permissions from role assignments and key scopes held in PostgreSQL."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def resolve(self, principal_id: UUID, organization_id: UUID) -> frozenset[str]:
        role_granted = (
            select(permission.c.key)
            .select_from(
                membership.join(role, role.c.id == membership.c.role_id)
                .join(role_permission, role_permission.c.role_id == role.c.id)
                .join(permission, permission.c.id == role_permission.c.permission_id)
            )
            .where(
                membership.c.organization_id == organization_id,
                membership.c.status == ACTIVE_MEMBERSHIP,
                (membership.c.user_id == principal_id)
                | (membership.c.service_account_id == principal_id),
                (role.c.organization_id.is_(None)) | (role.c.organization_id == organization_id),
            )
        )
        key_granted = select(api_key_scope.c.scope).where(
            api_key_scope.c.api_key_id == principal_id,
            api_key_scope.c.organization_id == organization_id,
        )

        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                rows = (await uow.session.execute(union(role_granted, key_granted))).scalars().all()
                return frozenset(rows)
        except (SQLAlchemyError, OSError) as exc:
            # Deny, loudly. OSError covers a raw connection refusal that can surface before
            # SQLAlchemy's own exception translation applies - the same handling every other
            # storage adapter in this codebase uses.
            _logger.error(
                "permission_resolution_failed",
                error=type(exc).__name__,
                organization_id=str(organization_id),
            )
            return frozenset()
