"""Durable, tenant-scoped budget ledger for atomic reserve/commit (ADR-0017, Slice 9).

Adds org_budget / budget_reservation / cost_ledger — narrower, newly-named tables that do not
reuse the Phase-1 illustrative budget/reservation/usage_ledger tables from 0001_initial.sql (see
ADR-0017 for why: unused catalog/scope dimensions, and a uuid request_id incompatible with
InferenceRequest.correlation_id's str identity).

Revision ID: 0006_budget_ledger
Revises: 0005_rls_nullif_org_guc
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# Alembic loads version files by path, so resolve the shared helper from this file's location.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sql_script import execute_sql_script

revision: str = "0006_budget_ledger"
down_revision: str | None = "0005_rls_nullif_org_guc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0006_budget_ledger.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cost_ledger")
    op.execute("DROP TABLE IF EXISTS budget_reservation")
    op.execute("DROP TABLE IF EXISTS org_budget")
