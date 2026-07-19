"""Tenant-isolation (RLS) verification for auth repositories against real PostgreSQL.

Runs in Gate 2 / CI (skipped only when no Postgres URL is configured — see
``tests.support.postgres``). Per ADR-0014 the connection is the least-privilege ``app_rw``
role (NOSUPERUSER, NOBYPASSRLS); a superuser/BYPASSRLS connection would bypass RLS entirely
and make this test meaningless. ``test_database_role.py`` guards that precondition.

Isolation is asserted *symmetrically*: a credential is created in each of two tenants, and
each tenant must be unable to read the other's credential while still reading its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.repositories.auth_repositories import (
    SqlServiceAccountCredentialRepository,
)
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.domain.auth.models import ServiceAccountCredentialRecord
from gateway.shared.secrets import hash_secret
from tests.support.postgres import PG_URL, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]


async def _seed_org(uow_factory: UnitOfWorkFactory, org_id: UUID) -> None:
    """Insert an organization (not RLS-scoped) — the FK parent for its service accounts."""
    slug = f"t-{org_id.hex[:16]}"
    async with uow_factory(tenant_id=None) as uow:
        await uow.session.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org_id), "slug": slug, "name": f"tenant-{slug}"},
        )
        await uow.commit()


async def _seed_credential(uow_factory: UnitOfWorkFactory, org_id: UUID, client_id: str) -> None:
    """Insert a service account + credential *within* the tenant's RLS context."""
    service_account_id = uuid4()
    async with uow_factory(tenant_id=org_id) as uow:
        # service_account is RLS-scoped; WITH CHECK requires app.current_org == org_id,
        # which the UnitOfWork has bound on enter.
        await uow.session.execute(
            text(
                "INSERT INTO service_account (id, organization_id, name) VALUES (:id, :org, :name)"
            ),
            {"id": str(service_account_id), "org": str(org_id), "name": f"sa-{client_id}"},
        )
        await SqlServiceAccountCredentialRepository(uow.session).add(
            ServiceAccountCredentialRecord(
                id=uuid4(),
                service_account_id=service_account_id,
                organization_id=org_id,
                client_id=client_id,
                secret_hash=hash_secret("s3cret"),
                status="active",
            )
        )
        await uow.commit()


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


async def test_rls_enforces_symmetric_tenant_isolation(engine: AsyncEngine) -> None:
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    org_a, org_b = uuid4(), uuid4()
    client_a, client_b = f"cid-a-{uuid4().hex}", f"cid-b-{uuid4().hex}"

    for org in (org_a, org_b):
        await _seed_org(factory, org)
    await _seed_credential(factory, org_a, client_a)
    await _seed_credential(factory, org_b, client_b)

    # Each tenant reads its OWN credential (RLS USING clause permits it).
    async with factory(tenant_id=org_a) as uow:
        own_a = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(client_a)
    async with factory(tenant_id=org_b) as uow:
        own_b = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(client_b)
    assert own_a is not None
    assert own_b is not None

    # Tenant A must NOT read tenant B's credential, and vice versa (RLS blocks it).
    async with factory(tenant_id=org_a) as uow:
        cross_a_reads_b = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(
            client_b
        )
    async with factory(tenant_id=org_b) as uow:
        cross_b_reads_a = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(
            client_a
        )
    assert cross_a_reads_b is None
    assert cross_b_reads_a is None


async def test_rls_denies_read_without_tenant_context(engine: AsyncEngine) -> None:
    """Deny-by-default: with no app.current_org bound, RLS returns zero rows (ADR-0009)."""
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    org = uuid4()
    client = f"cid-none-{uuid4().hex}"
    await _seed_org(factory, org)
    await _seed_credential(factory, org, client)

    # rls_enabled but tenant_id=None → no set_config → deny-by-default filters all rows.
    async with factory(tenant_id=None) as uow:
        found = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(client)
    assert found is None


async def test_current_org_guc_empty_string_after_transaction_reset(engine: AsyncEngine) -> None:
    """Deny-by-default must hold on a REUSED pooled connection, not just a fresh one.

    ``set_config('app.current_org', ..., true)`` is transaction-local. Once that transaction
    commits, the GUC on that connection reads back as an EMPTY STRING rather than NULL. The
    original policy evaluated ``''::uuid`` and raised ``invalid_text_representation`` instead of
    matching zero rows, so deny-by-default *errored* rather than filtering (migration 0005 wraps
    the expression in NULLIF). This test pins that PostgreSQL behaviour and the fix.
    """
    factory = UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)
    org = uuid4()
    client = f"cid-guc-{uuid4().hex}"
    await _seed_org(factory, org)
    await _seed_credential(factory, org, client)

    # 1. Bind a tenant and commit - this is what leaves '' behind on the pooled connection.
    async with factory(tenant_id=org) as uow:
        assert (
            await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(client)
        ) is not None
        await uow.commit()

    # 2. Observe the GUC on that same (now reused) connection: '' rather than NULL.
    async with factory(tenant_id=None) as uow:
        raw = (
            await uow.session.execute(text("SELECT current_setting('app.current_org', true)"))
        ).scalar_one_or_none()
    assert raw is None or raw == "", f"expected NULL or empty GUC, got {raw!r}"

    # 3. The policy must now return ZERO ROWS - not raise invalid_text_representation.
    async with factory(tenant_id=None) as uow:
        leaked = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(client)
    assert leaked is None, "deny-by-default must filter, not error, on a reused connection"
