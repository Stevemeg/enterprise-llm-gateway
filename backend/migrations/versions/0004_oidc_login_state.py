"""OIDC login state: state/nonce/PKCE between /authorize and /callback (ADR-0015).

Tenant-scoped + RLS-protected; single-use enforced by atomic ``DELETE ... RETURNING``
on consume (see the StateStore adapter), TTL = 5 minutes with an active expiry sweep.

Revision ID: 0004_oidc_login_state
Revises: 0003_database_roles
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

revision: str = "0004_oidc_login_state"
down_revision: str | None = "0003_database_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0004_oidc_login_state.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS oidc_login_state")
