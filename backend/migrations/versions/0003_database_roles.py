"""Least-privilege runtime database role for RLS enforcement (ADR-0014).

Creates the ``app_rw`` role (NOSUPERUSER, NOBYPASSRLS) and its grants so the application's
request path is actually subject to Row-Level Security. Superuser/BYPASSRLS connections
bypass RLS even under FORCE, which would silently defeat tenant isolation (NFR-SEC07).
Realizes RLS_Strategy.md §4, deferred from Phase 3.

Revision ID: 0003_database_roles
Revises: 0002_service_account_credential
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

revision: str = "0003_database_roles"
down_revision: str | None = "0002_service_account_credential"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0003_database_roles.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Roles are cluster-global; revoke privileges and drop only if unused. Reassign first
    # so the DROP cannot fail on dependent objects (defensive; app_rw owns nothing).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_rw;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    REVOKE USAGE, SELECT ON SEQUENCES FROM app_rw;
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM app_rw;
                REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM app_rw;
                REVOKE USAGE ON SCHEMA public FROM app_rw;
                DROP ROLE app_rw;
            END IF;
        END $$;
        """
    )
