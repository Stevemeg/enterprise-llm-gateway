"""Durable RBAC storage + hash-chained audit sink (ADR-0016 Slice 18, ADR-0019).

Seeds the ADR-0008 permission catalog / system roles / role->permission matrix (no migration had
ever seeded them), adds audit_chain_head and an audit_event DEFAULT partition, hardens every
partition of audit_event/usage_ledger against a verified cross-tenant read and append-only bypass,
and creates the ADR-0019 credential-bootstrap lookup.

Revision ID: 0007_rbac_seed_audit_chain
Revises: 0006_budget_ledger
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from alembic import op

# Alembic loads version files by path, so resolve the shared helper from this file's location.
sys.path.append(str(Path(__file__).resolve().parent.parent))

from sql_script import execute_sql_script

revision: str = "0007_rbac_seed_audit_chain"
down_revision: str | None = "0006_budget_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL_FILE = Path(__file__).resolve().parent.parent / "sql" / "0007_rbac_seed_audit_chain.sql"


def upgrade() -> None:
    execute_sql_script(op, _SQL_FILE.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS gateway_api_key_tenant(text)")
    op.execute("DROP POLICY IF EXISTS api_key_bootstrap_lookup ON api_key")
    op.execute("DROP TABLE IF EXISTS audit_chain_head")
    op.execute("DROP TABLE IF EXISTS audit_event_default")
    # The seeded reference data and the partition hardening are deliberately NOT reverted:
    # re-granting UPDATE/DELETE on an append-only log to undo a security fix would be a
    # downgrade that leaves the database less safe than before the upgrade ran.
