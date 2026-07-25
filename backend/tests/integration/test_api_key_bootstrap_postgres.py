"""ADR-0019 credential bootstrap, against real PostgreSQL (Slice 18).

The point of these tests is that the *exception* is as narrow as ADR-0019 claims. It is easy to
prove a lookup works; what matters is proving that granting it did not also grant anything else -
so the first assertions are that ``app_rw`` still cannot read ``api_key`` on its own, and that the
function refuses everything except an exact, active prefix.

Runs as ``app_rw`` (ADR-0014). A BYPASSRLS connection would make all of this vacuous.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.repositories.auth_repositories import (
    TenantScopedApiKeyRepository,
)
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.adapters.security.api_keys import generate_api_key
from gateway.application.auth.authenticate_api_key import AuthenticateApiKey
from gateway.domain.auth.errors import CredentialInvalidError
from gateway.domain.auth.models import PrincipalType
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_api_key, seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]


class _Clock:
    def now(self) -> object:
        from datetime import UTC, datetime

        return datetime(2026, 7, 25, tzinfo=UTC)


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


# ------------------------------------------------------------------ the exception stays narrow


async def test_the_runtime_role_still_cannot_read_api_key_without_a_tenant(
    factory: UnitOfWorkFactory,
) -> None:
    """The premise of ADR-0019, asserted rather than assumed: RLS was NOT relaxed to make the
    lookup work. If this ever returns rows, the bootstrap function stopped being the only way in
    and the whole design has quietly collapsed into Option B (rejected)."""
    org = uuid4()
    await seed_organization(factory, org)
    minted = generate_api_key()
    await seed_api_key(factory, org, prefix=minted.prefix, key_hash=minted.key_hash)

    async with factory(tenant_id=None) as uow:
        visible = (await uow.session.execute(text("SELECT count(*) FROM api_key"))).scalar_one()
    assert visible == 0


async def test_the_bootstrap_function_discloses_only_the_organization(
    factory: UnitOfWorkFactory,
) -> None:
    """It returns a uuid, not a row. There is no projection through which a hash or a scope could
    escape, which is what makes the exception reviewable."""
    org = uuid4()
    await seed_organization(factory, org)
    minted = generate_api_key()
    await seed_api_key(factory, org, prefix=minted.prefix, key_hash=minted.key_hash)

    async with factory(tenant_id=None) as uow:
        resolved = (
            await uow.session.execute(
                text("SELECT gateway_api_key_tenant(:p)"), {"p": minted.prefix}
            )
        ).scalar_one()
    assert resolved == org


@pytest.mark.parametrize("probe", ["elg_live_nosuchkey", "", "elg_"])
async def test_an_unknown_prefix_resolves_to_nothing(
    factory: UnitOfWorkFactory, probe: str
) -> None:
    """Exact match only - no prefix-of-a-prefix, no enumeration."""
    async with factory(tenant_id=None) as uow:
        assert (
            await uow.session.execute(text("SELECT gateway_api_key_tenant(:p)"), {"p": probe})
        ).scalar_one() is None


async def test_a_partial_prefix_does_not_match_a_real_key(factory: UnitOfWorkFactory) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    minted = generate_api_key()
    await seed_api_key(factory, org, prefix=minted.prefix, key_hash=minted.key_hash)

    async with factory(tenant_id=None) as uow:
        assert (
            await uow.session.execute(
                text("SELECT gateway_api_key_tenant(:p)"), {"p": minted.prefix[:8]}
            )
        ).scalar_one() is None


async def test_a_revoked_key_is_not_resolvable(factory: UnitOfWorkFactory) -> None:
    """``status = 'active'`` is inside the function, so a revoked key cannot even reach phase 2."""
    org = uuid4()
    await seed_organization(factory, org)
    minted = generate_api_key()
    await seed_api_key(
        factory, org, prefix=minted.prefix, key_hash=minted.key_hash, status="revoked"
    )
    assert await TenantScopedApiKeyRepository(factory).get_by_prefix(minted.prefix) is None


# ------------------------------------------------------------------ the two-phase repository


async def test_the_repository_returns_the_record_from_inside_the_tenants_context(
    factory: UnitOfWorkFactory,
) -> None:
    org = uuid4()
    await seed_organization(factory, org)
    minted = generate_api_key()
    key_id = await seed_api_key(
        factory,
        org,
        prefix=minted.prefix,
        key_hash=minted.key_hash,
        scopes=("inference:invoke",),
    )

    record = await TenantScopedApiKeyRepository(factory).get_by_prefix(minted.prefix)
    assert record is not None
    assert record.id == key_id
    assert record.organization_id == org
    assert record.scopes == ("inference:invoke",)
    assert record.is_active


async def test_an_unknown_prefix_ends_at_phase_one(factory: UnitOfWorkFactory) -> None:
    assert await TenantScopedApiKeyRepository(factory).get_by_prefix("elg_live_absent1") is None


async def test_the_full_use_case_authenticates_and_rejects_a_wrong_secret(
    factory: UnitOfWorkFactory,
) -> None:
    """End of the credential path: the tenant is resolved, the record is read under RLS, and the
    presented secret is then verified in constant time."""
    org = uuid4()
    await seed_organization(factory, org)
    minted = generate_api_key()
    key_id = await seed_api_key(
        factory,
        org,
        prefix=minted.prefix,
        key_hash=minted.key_hash,
        scopes=("inference:invoke",),
    )
    authenticate = AuthenticateApiKey(TenantScopedApiKeyRepository(factory), _Clock())  # type: ignore[arg-type]

    principal = await authenticate(minted.secret)
    assert principal.principal_type is PrincipalType.API_KEY
    assert principal.subject_id == key_id
    assert principal.organization_id == org

    # Same prefix, wrong secret: the hash comparison is what refuses, not the lookup.
    forged = minted.prefix + "x" * 40
    with pytest.raises(CredentialInvalidError):
        await authenticate(forged)


async def test_a_database_failure_refuses_rather_than_admitting() -> None:
    """ADR-0009 rows 6 and 15: an unreadable credential store must deny."""
    unreachable = create_database_engine(url="postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        factory = UnitOfWorkFactory(create_session_factory(unreachable), rls_enabled=True)
        repository = TenantScopedApiKeyRepository(factory)
        assert await repository.get_by_prefix("elg_live_anything") is None
    finally:
        await unreachable.dispose()
