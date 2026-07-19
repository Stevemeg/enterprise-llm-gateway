"""Make tenant RLS policies null-safe on pooled connections.

`current_setting('app.current_org', true)` returns '' (not NULL) once a transaction-local
set_config has been reset, so `''::uuid` raised invalid_text_representation instead of matching
zero rows. Wrapping in NULLIF restores documented deny-by-default behaviour.

Revision ID: 0005_rls_nullif_org_guc
Revises: 0004_oidc_login_state
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# Alembic loads version files by path, so resolve the shared helper from this file's location.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sql_script import execute_sql_script

revision: str = "0005_rls_nullif_org_guc"
down_revision: str | None = "0004_oidc_login_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0005_rls_nullif_org_guc.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT tablename FROM pg_policies
                     WHERE schemaname = 'public'
                       AND policyname = tablename || '_tenant_isolation'
            LOOP
                EXECUTE format(
                    'DROP POLICY %I ON %I;',
                    r.tablename || '_tenant_isolation',
                    r.tablename);
                EXECUTE format(
                    $p$CREATE POLICY %1$s_tenant_isolation ON %1$I
                         USING (organization_id
                                = current_setting('app.current_org', true)::uuid)
                         WITH CHECK (organization_id
                                = current_setting('app.current_org', true)::uuid);$p$,
                    r.tablename);
            END LOOP;
        END $$;
        """
    )
