"""Partitions must enforce tenant isolation and immutability in their own right (Slice 18).

A partitioned table's RLS policies are **not** applied when a partition is named directly, and
migration 0003's append-only ``REVOKE`` was applied to the partitioned parents only. Together those
two facts meant that, before migration 0007, ``app_rw`` could read *and rewrite* another tenant's
``audit_event`` rows simply by naming ``audit_event_2026_07`` instead of ``audit_event``:

    as app_rw, tenant B bound, against a row owned by tenant A
      SELECT count(*) FROM audit_event          -> 0    (parent policy enforced)
      SELECT count(*) FROM audit_event_2026_07  -> 1    <-- cross-tenant read
      UPDATE audit_event_2026_07 SET action=... -> 1    <-- append-only bypass

Nothing had ever written ``audit_event``, so nothing had ever exercised it. This is the regression
test for the fix, and it is written structurally - over whatever partitions actually exist - so a
future partition added without hardening fails here rather than shipping the hole again.

Runs as ``app_rw`` (ADR-0014); a BYPASSRLS connection would make every assertion vacuous, which
``test_database_role.py`` independently guards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.audit.sql_sink import SqlAuthAuditSink
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.domain.auth.models import AuthAuditEvent
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]

#: Both are append-only, tenant-scoped and RANGE-partitioned (FR-113/114, NFR-SEC09).
_PARTITIONED_PARENTS = ("audit_event", "usage_ledger")

_PARTITIONS_SQL = text(
    """
    SELECT child.relname AS partition,
           child.relrowsecurity AS rls_enabled,
           child.relforcerowsecurity AS rls_forced,
           parent.relname AS parent
    FROM pg_inherits i
    JOIN pg_class child  ON child.oid  = i.inhrelid
    JOIN pg_class parent ON parent.oid = i.inhparent
    WHERE parent.relname = ANY(:parents)
    """
)


class _Frozen:
    def now(self) -> datetime:
        return datetime(2026, 7, 25, 10, 30, 0, tzinfo=UTC)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def factory(engine: AsyncEngine) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)


async def _partitions(factory: UnitOfWorkFactory) -> list[dict[str, object]]:
    async with factory(tenant_id=None) as uow:
        rows = (
            await uow.session.execute(_PARTITIONS_SQL, {"parents": list(_PARTITIONED_PARENTS)})
        ).mappings()
        found = [dict(row) for row in rows]
    assert found, "no partitions found - this test would otherwise assert nothing"
    return found


async def test_every_partition_enables_and_forces_rls_of_its_own(
    factory: UnitOfWorkFactory,
) -> None:
    unprotected = [
        p["partition"]
        for p in await _partitions(factory)
        if not (p["rls_enabled"] and p["rls_forced"])
    ]
    assert not unprotected, (
        f"partitions without their own RLS: {unprotected}. A parent's policies do NOT apply when "
        "a partition is named directly, so these are readable across tenants."
    )


async def test_every_partition_has_its_own_tenant_isolation_policy(
    factory: UnitOfWorkFactory,
) -> None:
    """ENABLE+FORCE with no policy denies everything, which is safe but breaks the app. The
    policy is what makes the isolation correct rather than merely closed."""
    partitions = await _partitions(factory)
    async with factory(tenant_id=None) as uow:
        policied = set(
            (
                await uow.session.execute(
                    text("SELECT tablename FROM pg_policies WHERE schemaname = 'public'")
                )
            )
            .scalars()
            .all()
        )
    missing = [p["partition"] for p in partitions if p["partition"] not in policied]
    assert not missing, f"partitions with no tenant-isolation policy: {missing}"


async def test_the_runtime_role_holds_no_update_or_delete_on_any_partition(
    factory: UnitOfWorkFactory,
) -> None:
    """Append-only is a privilege, not an intention. The parents' REVOKE does not reach here."""
    partitions = await _partitions(factory)
    async with factory(tenant_id=None) as uow:
        writable = []
        for partition in partitions:
            for privilege in ("UPDATE", "DELETE"):
                granted = (
                    await uow.session.execute(
                        text("SELECT has_table_privilege(current_user, :rel, :priv)"),
                        {"rel": str(partition["partition"]), "priv": privilege},
                    )
                ).scalar_one()
                if granted:
                    writable.append(f"{partition['partition']}.{privilege}")
    assert not writable, f"append-only bypass available on: {writable}"


async def test_a_tenant_cannot_read_another_tenants_audit_row_through_a_partition(
    factory: UnitOfWorkFactory,
) -> None:
    """The behavioural half. Structural checks can be satisfied by a policy that is present but
    wrong; this asserts the outcome the policy exists to produce."""
    victim, attacker = uuid4(), uuid4()
    for org in (victim, attacker):
        await seed_organization(factory, org)
    await SqlAuthAuditSink(factory, _Frozen()).record(
        AuthAuditEvent(
            action="request.authenticated",
            result="success",
            organization_id=victim,
            principal_type="api_key",
            subject_id=uuid4(),
        )
    )

    # Sanity: the row really exists, or the isolation assertion below proves nothing.
    async with factory(tenant_id=victim) as uow:
        assert (
            await uow.session.execute(
                text("SELECT count(*) FROM audit_event WHERE organization_id = :org"),
                {"org": str(victim)},
            )
        ).scalar_one() == 1

    async with factory(tenant_id=attacker) as uow:
        for relation in ("audit_event", "audit_event_2026_07", "audit_event_default"):
            visible = (
                await uow.session.execute(text(f"SELECT count(*) FROM {relation}"))
            ).scalar_one()
            assert visible == 0, f"cross-tenant read via {relation}"


async def test_a_tenant_cannot_rewrite_another_tenants_audit_row_through_a_partition(
    factory: UnitOfWorkFactory,
) -> None:
    victim = uuid4()
    await seed_organization(factory, victim)
    await SqlAuthAuditSink(factory, _Frozen()).record(
        AuthAuditEvent(action="request.authenticated", result="success", organization_id=victim)
    )
    with pytest.raises(SQLAlchemyError) as caught:
        await _tamper(factory)
    assert "permission denied" in str(caught.value).lower()


async def _tamper(factory: UnitOfWorkFactory) -> None:
    async with factory(tenant_id=uuid4()) as uow:
        await uow.session.execute(text("UPDATE audit_event_default SET action = 'tampered'"))
        await uow.commit()
