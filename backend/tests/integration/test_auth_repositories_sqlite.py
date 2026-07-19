"""Integration tests for the SQLAlchemy auth repositories (real SQLite via the UoW).

Exercises CRUD, transaction commit, rollback, and the auth-flow behaviours the repositories
support. Postgres + RLS are covered in test_auth_rls_postgres.py (CI / Gate 2).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence import tables
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.repositories.auth_repositories import (
    SqlApiKeyRepository,
    SqlOAuthIdentityRepository,
    SqlRefreshTokenRepository,
    SqlServiceAccountCredentialRepository,
    SqlSessionRepository,
)
from gateway.adapters.persistence.tables import auth_metadata
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.adapters.security.api_keys import generate_api_key
from gateway.domain.auth.models import (
    ApiKeyStatus,
    OAuthIdentityRecord,
    RefreshTokenRecord,
    ServiceAccountCredentialRecord,
    SessionRecord,
)
from gateway.shared.secrets import generate_token, hash_secret
from tests.conftest import FixedClock

pytestmark = pytest.mark.integration


async def _engine(tmp_path: Path) -> AsyncEngine:
    engine = create_database_engine(url=f"sqlite+aiosqlite:///{tmp_path}/auth.db")
    async with engine.begin() as conn:
        await conn.run_sync(auth_metadata.create_all)
    return engine


def _uow(engine: AsyncEngine) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(create_session_factory(engine), rls_enabled=False)


async def test_api_key_lookup_returns_record_with_scopes(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    key = generate_api_key()
    org, key_id = uuid4(), uuid4()
    async with _uow(engine)() as uow:
        await uow.session.execute(
            insert(tables.api_key).values(
                id=key_id,
                organization_id=org,
                name="k",
                key_prefix=key.prefix,
                key_hash=bytes.fromhex(key.key_hash),
                status=ApiKeyStatus.ACTIVE,
            )
        )
        await uow.session.execute(
            insert(tables.api_key_scope).values(
                api_key_id=key_id, scope="infer:chat", organization_id=org
            )
        )
        await uow.commit()
    async with _uow(engine)() as uow:
        record = await SqlApiKeyRepository(uow.session).get_by_prefix(key.prefix)
    assert record is not None
    assert record.key_hash == key.key_hash
    assert record.scopes == ("infer:chat",)
    assert record.is_active
    await engine.dispose()


async def test_service_account_credential_crud_and_revoke(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    cred = ServiceAccountCredentialRecord(
        id=uuid4(),
        service_account_id=uuid4(),
        organization_id=uuid4(),
        client_id="client-1",
        secret_hash=hash_secret("s3cret"),
        status="active",
    )
    async with _uow(engine)() as uow:
        await SqlServiceAccountCredentialRepository(uow.session).add(cred)
        await uow.commit()
    async with _uow(engine)() as uow:
        repo = SqlServiceAccountCredentialRepository(uow.session)
        fetched = await repo.get_by_client_id("client-1")
        assert fetched is not None
        assert fetched.secret_hash == cred.secret_hash
        await repo.revoke(cred.id)
        await uow.commit()
    async with _uow(engine)() as uow:
        revoked = await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id(
            "client-1"
        )
    assert revoked is not None
    assert revoked.status == "revoked"
    await engine.dispose()


async def test_session_and_refresh_token_lifecycle(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    clock = FixedClock()
    org, user, sid = uuid4(), uuid4(), uuid4()
    session = SessionRecord(
        id=sid,
        user_id=user,
        organization_id=org,
        created_at=clock.now(),
        expires_at=clock.now() + timedelta(days=1),
    )
    secret = generate_token()
    token = RefreshTokenRecord(
        id=uuid4(),
        session_id=sid,
        organization_id=org,
        token_hash=hash_secret(secret),
        expires_at=clock.now() + timedelta(days=7),
    )
    async with _uow(engine)() as uow:
        await SqlSessionRepository(uow.session, clock).add(session)
        await SqlRefreshTokenRepository(uow.session, clock).add(token)
        await uow.commit()
    async with _uow(engine)() as uow:
        got = await SqlRefreshTokenRepository(uow.session, clock).get_by_hash(hash_secret(secret))
        assert got is not None
        assert got.session_id == sid
    # revoke session tokens marks revoked_at
    async with _uow(engine)() as uow:
        await SqlRefreshTokenRepository(uow.session, clock).revoke_session_tokens(sid)
        await SqlSessionRepository(uow.session, clock).revoke(sid)
        await uow.commit()
    async with _uow(engine)() as uow:
        revoked_token = await SqlRefreshTokenRepository(uow.session, clock).get_by_hash(
            hash_secret(secret)
        )
        revoked_session = await SqlSessionRepository(uow.session, clock).get(sid)
    assert revoked_token is not None
    assert revoked_token.revoked_at is not None
    assert revoked_session is not None
    assert revoked_session.revoked_at is not None
    await engine.dispose()


async def test_rollback_discards_writes(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    cred = ServiceAccountCredentialRecord(
        id=uuid4(),
        service_account_id=uuid4(),
        organization_id=uuid4(),
        client_id="rollback",
        secret_hash=hash_secret("x"),
        status="active",
    )

    async def _add_then_fail() -> None:
        async with _uow(engine)() as uow:
            await SqlServiceAccountCredentialRepository(uow.session).add(cred)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _add_then_fail()
    async with _uow(engine)() as uow:
        assert (
            await SqlServiceAccountCredentialRepository(uow.session).get_by_client_id("rollback")
            is None
        )
    await engine.dispose()


async def test_oauth_identity_lookup(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    record = OAuthIdentityRecord(
        id=uuid4(), organization_id=uuid4(), user_id=uuid4(), provider="okta", subject="sub-1"
    )
    async with _uow(engine)() as uow:
        await SqlOAuthIdentityRepository(uow.session).add(record)
        await uow.commit()
    async with _uow(engine)() as uow:
        found = await SqlOAuthIdentityRepository(uow.session).get_by_subject("okta", "sub-1")
        missing = await SqlOAuthIdentityRepository(uow.session).get_by_subject("okta", "nope")
    assert found is not None
    assert found.user_id == record.user_id
    assert missing is None
    await engine.dispose()
