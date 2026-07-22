"""SQLAlchemy Core table definitions for the budget ledger (ADR-0017, Slice 9).

Kept separate from ``tables.py`` (scoped to the authentication tables) rather than appended to
it. Authoritative DDL is ``migrations/sql/0006_budget_ledger.sql``; these describe the columns the
adapter queries. ``Numeric`` uses Python ``Decimal`` end-to-end (asyncpg maps ``numeric`` to
``Decimal`` natively) so no float ever enters the path between ``Money`` and the database.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, Integer, MetaData, Numeric, String, Table, Text, Uuid

ledger_metadata = MetaData()

# Bound to the existing PostgreSQL ENUM ``reservation_status`` (owned by 0001_initial.sql, never
# created from here) - the same type the pre-existing illustrative `reservation` table uses.
_RESERVATION_STATUS = Enum(
    "reserved",
    "committed",
    "released",
    "expired",
    name="reservation_status",
    create_type=False,
)

org_budget = Table(
    "org_budget",
    ledger_metadata,
    Column("organization_id", Uuid, primary_key=True),
    Column("amount_limit", Numeric(18, 8), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("reserved", Numeric(18, 8), nullable=False),
    Column("spent", Numeric(18, 8), nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

budget_reservation = Table(
    "budget_reservation",
    ledger_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("estimated_cost", Numeric(18, 8), nullable=False),
    Column("actual_cost", Numeric(18, 8)),
    Column("currency", String(3), nullable=False),
    Column("status", _RESERVATION_STATUS, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("settled_at", DateTime(timezone=True)),
)

cost_ledger = Table(
    "cost_ledger",
    ledger_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("input_cost", Numeric(18, 8), nullable=False),
    Column("output_cost", Numeric(18, 8), nullable=False),
    Column("total_cost", Numeric(18, 8), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("created_at", DateTime(timezone=True)),
)
