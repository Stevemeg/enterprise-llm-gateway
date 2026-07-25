"""SQLAlchemy Core table definitions for the RBAC tables (ADR-0008, ADR-0016 Slice 18).

Kept separate from ``tables.py`` (authentication) and ``ledger_tables.py`` (budget), matching how
each capability owns the description of the columns it queries. The authoritative DDL is
``Schema.sql`` / the migrations; these describe the read shape ``SqlPermissionResolver`` uses.

Only the columns the resolver actually reads are declared. ``membership.created_at``,
``role.name`` and ``permission.description`` exist in the schema and are deliberately absent here:
a query interface that lists columns nothing selects invites someone to start selecting them.

``membership.status`` binds to the existing PostgreSQL ``membership_status`` ENUM rather than
``String``. Declaring it as text makes asyncpg send text where an enum is expected, which
PostgreSQL rejects outright - the same trap ``tables.py`` documents for ``api_key_status``.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Enum, MetaData, Table, Text, Uuid

rbac_metadata = MetaData()

#: Bound to the existing PostgreSQL ENUM (owned by 0001_initial.sql, never created from here).
_MEMBERSHIP_STATUS = Enum(
    "invited",
    "active",
    "disabled",
    name="membership_status",
    create_type=False,
)

#: The only membership status that grants anything. ``invited`` has not accepted and ``disabled``
#: has been switched off; both must resolve to no permissions, so this is a security constant
#: rather than a query detail.
ACTIVE_MEMBERSHIP = "active"

role = Table(
    "role",
    rbac_metadata,
    Column("id", Uuid, primary_key=True),
    # NULL => global system role (ADR-0008). This is why `role` carries no RLS policy and is
    # exempt from the tenant-table guardrail: it is partly global reference data.
    Column("organization_id", Uuid),
    Column("key", Text, nullable=False),
    Column("is_system", Boolean, nullable=False),
)

permission = Table(
    "permission",
    rbac_metadata,
    Column("id", Uuid, primary_key=True),
    Column("key", Text, nullable=False),
)

role_permission = Table(
    "role_permission",
    rbac_metadata,
    Column("role_id", Uuid, primary_key=True),
    Column("permission_id", Uuid, primary_key=True),
)

membership = Table(
    "membership",
    rbac_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("user_id", Uuid),
    Column("service_account_id", Uuid),
    Column("role_id", Uuid, nullable=False),
    Column("status", _MEMBERSHIP_STATUS, nullable=False),
)
