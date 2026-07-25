"""Durable RBAC resolution against real PostgreSQL (ADR-0008, ADR-0016 Slice 18).

Runs in Gate 2 / CI as the least-privilege ``app_rw`` role (ADR-0014), so every assertion about
tenant isolation is an assertion about RLS actually enforcing it - not about a WHERE clause the
adapter happens to include.

Failure-first, deliberately: every path that could plausibly end in "granted by accident" -
unknown principal, wrong tenant, inactive membership, another tenant's role, a revoked key - is
asserted to resolve to the empty set before any grant is asserted at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.authorization.sql_resolver import SqlPermissionResolver
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import (
    seed_api_key,
    seed_custom_role,
    seed_member,
    seed_organization,
    system_role_id,
)

pytestmark = [pytest.mark.integration, requires_postgres]


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


# ------------------------------------------------------------------ fail closed (first)


async def test_an_unknown_principal_resolves_to_nothing(factory: UnitOfWorkFactory) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    assert await SqlPermissionResolver(factory).resolve(uuid4(), org) == frozenset()


async def test_a_principal_resolves_to_nothing_in_a_tenant_they_do_not_belong_to(
    factory: UnitOfWorkFactory,
) -> None:
    """The isolation boundary: the same principal id, asked about the wrong organization.

    RLS filters ``membership`` to the bound tenant, so the row simply is not visible - which is
    why this holds even though the adapter would also have excluded it by WHERE clause.
    """
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        await seed_organization(factory, org)
    admin = await seed_member(factory, org_a, "admin")

    resolver = SqlPermissionResolver(factory)
    assert "audit:read" in await resolver.resolve(admin, org_a)
    assert await resolver.resolve(admin, org_b) == frozenset()


@pytest.mark.parametrize("status", ["invited", "disabled"])
async def test_a_membership_that_is_not_active_grants_nothing(
    factory: UnitOfWorkFactory, status: str
) -> None:
    """``invited`` has not accepted and ``disabled`` was switched off. Either granting would be a
    silent privilege leak that no other control would catch."""
    org = uuid4()
    await seed_organization(factory, org)
    member = await seed_member(factory, org, "owner", status=status)
    assert await SqlPermissionResolver(factory).resolve(member, org) == frozenset()


async def test_a_membership_pointing_at_another_tenants_custom_role_grants_nothing(
    factory: UnitOfWorkFactory,
) -> None:
    """No composite foreign key prevents this, and RLS on ``membership`` cannot catch it because
    the offending column is on ``role``. The resolver's explicit predicate is the only thing that
    does - so it is proven here rather than assumed."""
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        await seed_organization(factory, org)
    foreign_role = await seed_custom_role(factory, org_b, f"custom-{uuid4().hex[:8]}")
    member = await seed_member(factory, org_a, "developer", role_id=foreign_role)

    assert await SqlPermissionResolver(factory).resolve(member, org_a) == frozenset()


async def test_a_key_resolves_to_nothing_in_another_tenant(factory: UnitOfWorkFactory) -> None:
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        await seed_organization(factory, org)
    key_id = await seed_api_key(
        factory,
        org_a,
        prefix=f"elg_live_{uuid4().hex[:7]}",
        scopes=("inference:invoke",),
    )
    assert await SqlPermissionResolver(factory).resolve(key_id, org_b) == frozenset()


# ------------------------------------------------------------------ the seeded ADR-0008 matrix


async def test_the_adr_0008_role_matrix_is_seeded_and_resolved(
    factory: UnitOfWorkFactory,
) -> None:
    """Each role resolves to exactly the permissions ADR-0008's table gives it.

    Asserted as full set equality rather than membership: a role that quietly acquired an extra
    permission is exactly the drift this pins, and ``assert x in granted`` would never see it.
    """
    expected = {
        "owner": {
            "tenant:manage",
            "team:manage",
            "member:invite",
            "key:issue",
            "key:revoke",
            "provider:write",
            "model:write",
            "routing:write",
            "policy:write",
            "budget:write",
            "budget:read",
            "usage:read",
            "audit:read",
        },
        "admin": {
            "team:manage",
            "member:invite",
            "key:issue",
            "key:revoke",
            "provider:write",
            "model:write",
            "routing:write",
            "policy:write",
            "budget:write",
            "budget:read",
            "usage:read",
            "audit:read",
        },
        "operator": {
            "provider:write",
            "model:write",
            "routing:write",
            "policy:write",
            "budget:read",
            "usage:read",
        },
        "finance": {"budget:write", "budget:read", "usage:read"},
        "auditor": {"budget:read", "usage:read", "audit:read"},
        "developer": {"budget:read", "usage:read"},
    }
    org = uuid4()
    await seed_organization(factory, org)
    resolver = SqlPermissionResolver(factory)

    for role_key, permissions in expected.items():
        member = await seed_member(factory, org, role_key)
        assert await resolver.resolve(member, org) == frozenset(permissions), role_key


async def test_no_human_role_can_invoke_inference(factory: UnitOfWorkFactory) -> None:
    """ADR-0008: "infer:chat / infer:embed (via keys) - application principals only".

    This is why Slice 18 had to wire API-key verification as well: durable RBAC alone would have
    left the inference endpoint with no principal type that could ever be authorized.
    """
    org = uuid4()
    await seed_organization(factory, org)
    resolver = SqlPermissionResolver(factory)
    for role_key in ("owner", "admin", "operator", "finance", "auditor", "developer"):
        member = await seed_member(factory, org, role_key)
        assert "inference:invoke" not in await resolver.resolve(member, org), role_key


async def test_a_virtual_key_resolves_to_its_scopes(factory: UnitOfWorkFactory) -> None:
    """The second principal shape. No principal-type parameter was needed: ``api_key.id`` and
    ``app_user.id`` are distinct UUIDs, so at most one branch of the union can match."""
    org = uuid4()
    await seed_organization(factory, org)
    key_id = await seed_api_key(
        factory,
        org,
        prefix=f"elg_live_{uuid4().hex[:7]}",
        scopes=("inference:invoke",),
    )
    assert await SqlPermissionResolver(factory).resolve(key_id, org) == frozenset(
        {"inference:invoke"}
    )


async def test_multiple_roles_union_rather_than_override(factory: UnitOfWorkFactory) -> None:
    """A principal may hold several roles (schema: ``membership_user_role_key`` is per role)."""
    org = uuid4()
    await seed_organization(factory, org)
    member = await seed_member(factory, org, "auditor")
    async with factory(tenant_id=org) as uow:
        from sqlalchemy import text

        await uow.session.execute(
            text(
                "INSERT INTO membership (id, organization_id, user_id, role_id, status) "
                "VALUES (:id, :org, :user, :role, 'active')"
            ),
            {
                "id": str(uuid4()),
                "org": str(org),
                "user": str(member),
                "role": str(await system_role_id(factory, "finance")),
            },
        )
        await uow.commit()

    granted = await SqlPermissionResolver(factory).resolve(member, org)
    assert {"audit:read", "budget:write"} <= granted


# ------------------------------------------------------------------ fail closed on outage


async def test_a_database_failure_denies_rather_than_raising() -> None:
    """The port promises never to raise, so an outage must resolve to the empty set - which
    denies. A resolver that raised would surface as a 500 and, worse, tempt a caller into
    catching it and continuing."""
    unreachable = create_database_engine(url="postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        factory = UnitOfWorkFactory(create_session_factory(unreachable), rls_enabled=True)
        assert await SqlPermissionResolver(factory).resolve(uuid4(), uuid4()) == frozenset()
    finally:
        await unreachable.dispose()
