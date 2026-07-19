"""Initial schema — applies the canonical DDL from Schema.sql.

The full 40-table schema (tenancy + RLS, reserve/commit ledger, pgvector cache, audit,
etc.) lives in ``migrations/sql/0001_initial.sql`` (a copy of the reviewed ``docs/Schema.sql``,
DB-DEC-*). Executing it as one script preserves extension/enum/table/index/RLS ordering.

Revision ID: 0001_initial_schema
Revises:
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# Alembic loads version files by path, so the migrations package is not reliably importable.
# Resolve the shared helper from this file's own location instead of trusting sys.path.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sql_script import execute_sql_script

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0001_initial.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Initial migration: reset the public schema (destructive, as expected for a baseline).
    op.execute("DROP SCHEMA public CASCADE")
    op.execute("CREATE SCHEMA public")
