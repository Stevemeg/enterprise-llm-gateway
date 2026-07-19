"""Regression guard: the application must connect as the least-privilege runtime role.

ADR-0014 — PostgreSQL RLS (even with FORCE) is bypassed by superusers and BYPASSRLS roles.
Tenant isolation (NFR-SEC07) therefore depends on the app connecting as ``app_rw``
(NOSUPERUSER, NOBYPASSRLS). If someone later points the app back at a superuser (e.g. the
``gateway`` owner), this test fails immediately in Gate 2 / CI — before that config can ship.

Runs against the same URL the app uses (``GATEWAY_DATABASE__URL``); skipped only when no
Postgres is configured. See RLS_Strategy.md §7 (bypass containment).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine
from tests.support.postgres import PG_URL, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]

_EXPECTED_ROLE = "app_rw"
_FORBIDDEN_ROLE = "gateway"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


async def test_connection_uses_app_rw_role(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        current_user = (await conn.execute(text("SELECT current_user"))).scalar_one()
    assert current_user == _EXPECTED_ROLE, (
        f"app connected as {current_user!r}; must be {_EXPECTED_ROLE!r} (ADR-0014)"
    )
    assert current_user != _FORBIDDEN_ROLE


async def test_runtime_role_is_not_superuser_and_not_bypassrls(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()
    rolsuper, rolbypassrls = bool(row[0]), bool(row[1])
    assert rolsuper is False, "runtime role must NOT be a superuser (RLS would be bypassed)"
    assert rolbypassrls is False, "runtime role must NOT have BYPASSRLS (RLS would be bypassed)"


async def test_rls_is_enabled_and_forced_on_tenant_table(engine: AsyncEngine) -> None:
    """A representative tenant table must have RLS both ENABLED and FORCED."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'service_account_credential'"
                )
            )
        ).one()
    relrowsecurity, relforcerowsecurity = bool(row[0]), bool(row[1])
    assert relrowsecurity is True, "RLS must be ENABLED on service_account_credential"
    assert relforcerowsecurity is True, "RLS must be FORCED (owner is not exempt)"
