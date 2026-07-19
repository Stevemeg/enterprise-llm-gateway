"""Regression guard: future tenant tables auto-grant to app_rw (ADR-0014).

Migration 0003 runs ``ALTER DEFAULT PRIVILEGES ... GRANT ... TO app_rw`` so that any table
later created by the owner is automatically reachable by the least-privilege runtime role.
Without it, a new migration's table would silently become inaccessible to the app (or, worse,
be reachable only via a BYPASSRLS role). This test creates a real table *as the owner* and
asserts app_rw received exactly the expected DML — catching drift if the default privileges
are ever dropped or a future migration changes the owner.

Requires the owner URL (GATEWAY_MIGRATION_DATABASE__URL); skipped otherwise. The runtime
``app_rw`` role cannot create tables, by design.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine
from tests.support.postgres import OWNER_URL, requires_postgres_owner

pytestmark = [pytest.mark.integration, requires_postgres_owner]

_RUNTIME_ROLE = "app_rw"
_EXPECTED_PRIVS = ("SELECT", "INSERT", "UPDATE", "DELETE")


@pytest.fixture
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    assert OWNER_URL is not None  # guarded by requires_postgres_owner
    engine = create_database_engine(url=OWNER_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_new_owner_table_auto_grants_app_rw(owner_engine: AsyncEngine) -> None:
    # Unique, disposable table name in the public schema (default privileges are schema-scoped).
    table = f"_dp_probe_{uuid4().hex[:12]}"
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
    try:
        async with owner_engine.connect() as conn:
            granted = {
                priv: bool(
                    (
                        await conn.execute(
                            text("SELECT has_table_privilege(:role, :tbl, :priv)"),
                            {"role": _RUNTIME_ROLE, "tbl": table, "priv": priv},
                        )
                    ).scalar_one()
                )
                for priv in _EXPECTED_PRIVS
            }
        missing = [p for p, ok in granted.items() if not ok]
        assert not missing, (
            f"{_RUNTIME_ROLE} did not auto-receive {missing} on a new owner table — "
            "ALTER DEFAULT PRIVILEGES drift (ADR-0014 / migration 0003)"
        )
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
