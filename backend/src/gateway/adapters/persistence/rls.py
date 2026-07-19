"""Tenant Row-Level-Security context propagation (ADR-0002, RLS_Strategy.md).

Binds the request's organization to the DB session so PostgreSQL RLS policies filter
every query. We use ``set_config('app.current_org', :org, true)`` — the parameterizable,
injection-safe equivalent of ``SET LOCAL app.current_org`` (the ``true`` = local to the
transaction). Deny-by-default: if unset, RLS policies match no rows.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncSession

_TENANT_SETTING = "app.current_org"


def tenant_scope_statement(tenant_id: UUID) -> TextClause:
    """Return the transaction-local statement that binds the tenant for RLS."""
    return text("SELECT set_config(:name, :org, true)").bindparams(
        name=_TENANT_SETTING, org=str(tenant_id)
    )


async def bind_tenant(session: AsyncSession, tenant_id: UUID) -> None:
    """Execute the tenant-scope binding on the session's current transaction."""
    await session.execute(tenant_scope_statement(tenant_id))
