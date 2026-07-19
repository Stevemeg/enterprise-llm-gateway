"""Service-account client-credential storage (ADR-0013).

Adds ``service_account_credential`` (hashed, rotatable, RLS-scoped) so service accounts can
authenticate via client credentials — the Phase-3 schema had no credential column.

Revision ID: 0002_service_account_credential
Revises: 0001_initial_schema
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

revision: str = "0002_service_account_credential"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0002_service_account_credential.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS service_account_credential")
