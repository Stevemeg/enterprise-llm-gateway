"""Seeding helpers for the RBAC / audit integration tests (ADR-0016 Slice 18).

There is deliberately no role-management or key-issuance API in Slice 18, so tests seed the same
way an operator would: direct inserts, each inside the tenant's own RLS context so the ``WITH
CHECK`` clause has to accept them. That is itself worth something - a seed that RLS rejected would
mean the test was writing rows the application could never write.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text

from gateway.adapters.persistence.uow import UnitOfWorkFactory


async def seed_organization(factory: UnitOfWorkFactory, org_id: UUID) -> None:
    """Insert an organization. Not RLS-scoped - it is the parent every tenant row hangs from."""
    async with factory(tenant_id=None) as uow:
        await uow.session.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org_id), "slug": f"t-{org_id.hex[:16]}", "name": f"tenant-{org_id.hex[:8]}"},
        )
        await uow.commit()


async def system_role_id(factory: UnitOfWorkFactory, role_key: str) -> UUID:
    """Resolve a seeded system role by key. ``role`` is global reference data (no RLS)."""
    async with factory(tenant_id=None) as uow:
        role_id: UUID | None = (
            await uow.session.execute(
                text("SELECT id FROM role WHERE organization_id IS NULL AND key = :key"),
                {"key": role_key},
            )
        ).scalar_one_or_none()
    assert role_id is not None, f"migration 0007 did not seed the {role_key!r} system role"
    return role_id


async def seed_member(
    factory: UnitOfWorkFactory,
    org_id: UUID,
    role_key: str,
    *,
    status: str = "active",
    role_id: UUID | None = None,
) -> UUID:
    """Create a user in ``org_id`` holding ``role_key``; returns the user id (the principal id).

    ``role_id`` overrides the resolved role, which is how the cross-tenant-role test points a
    membership at a role belonging to somebody else.
    """
    user_id = uuid4()
    resolved = role_id if role_id is not None else await system_role_id(factory, role_key)
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text("INSERT INTO app_user (id, organization_id, email) VALUES (:id, :org, :email)"),
            {"id": str(user_id), "org": str(org_id), "email": f"{user_id.hex[:12]}@example.test"},
        )
        await uow.session.execute(
            text(
                "INSERT INTO membership (id, organization_id, user_id, role_id, status) "
                "VALUES (:id, :org, :user, :role, CAST(:status AS membership_status))"
            ),
            {
                "id": str(uuid4()),
                "org": str(org_id),
                "user": str(user_id),
                "role": str(resolved),
                "status": status,
            },
        )
        await uow.commit()
    return user_id


async def seed_custom_role(factory: UnitOfWorkFactory, org_id: UUID, key: str) -> UUID:
    """Create an org-owned (non-system) role granting ``inference:invoke``."""
    role_id = uuid4()
    async with factory(tenant_id=None) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO role (id, organization_id, key, name, is_system) "
                "VALUES (:id, :org, :key, :key, false)"
            ),
            {"id": str(role_id), "org": str(org_id), "key": key},
        )
        await uow.session.execute(
            text(
                "INSERT INTO role_permission (role_id, permission_id) "
                "SELECT :id, p.id FROM permission p WHERE p.key = 'inference:invoke'"
            ),
            {"id": str(role_id)},
        )
        await uow.commit()
    return role_id


async def seed_api_key(
    factory: UnitOfWorkFactory,
    org_id: UUID,
    *,
    prefix: str,
    key_hash: str | None = None,
    scopes: tuple[str, ...] = (),
    status: str = "active",
) -> UUID:
    """Create a virtual API key with scopes; returns the key id (the principal id).

    ``key_hash`` defaults to a fresh random digest because ``api_key_hash_key`` is UNIQUE
    **globally**, not per tenant: a hard-coded hash collides with itself across tenants and across
    re-runs against the same database. Tests that must verify a real secret pass the real hash.
    """
    key_id = uuid4()
    key_hash = key_hash if key_hash is not None else (uuid4().hex + uuid4().hex)
    async with factory(tenant_id=org_id) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO api_key (id, organization_id, name, key_prefix, key_hash, status) "
                "VALUES (:id, :org, :name, :prefix, DECODE(:hash, 'hex'), "
                "CAST(:status AS api_key_status))"
            ),
            {
                "id": str(key_id),
                "org": str(org_id),
                "name": f"key-{key_id.hex[:8]}",
                "prefix": prefix,
                "hash": key_hash,
                "status": status,
            },
        )
        for scope in scopes:
            await uow.session.execute(
                text(
                    "INSERT INTO api_key_scope (api_key_id, scope, organization_id) "
                    "VALUES (:id, :scope, :org)"
                ),
                {"id": str(key_id), "scope": scope, "org": str(org_id)},
            )
        await uow.commit()
    return key_id
