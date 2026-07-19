"""OIDC login-state store against real PostgreSQL (Gate 2 / CI) — ADR-0015.

Covers the guarantees the OIDC callback depends on: single-use consume, TTL expiry treated as
absent (fail closed), tenant isolation under RLS, the hygiene sweep, and — most importantly —
the **concurrent-callback race**: two callbacks presenting the same ``state`` must produce
exactly one winner. That is the whole reason consume is ``DELETE ... RETURNING`` rather than a
read-then-flag (Security_Test_Plan §1a rows 1-5).

Connects as the least-privilege ``app_rw`` role (ADR-0014), like the app itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.repositories.auth_repositories import SqlOidcLoginStateStore
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.domain.auth.models import OidcLoginStateRecord
from gateway.shared.secrets import sha256_hex
from tests.support.postgres import PG_URL, requires_postgres

pytestmark = [pytest.mark.integration, requires_postgres]

_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
_TTL = timedelta(minutes=5)  # ADR-0015: fixed 5-minute state TTL


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    assert PG_URL is not None  # guarded by requires_postgres
    eng = create_database_engine(url=PG_URL)
    try:
        yield eng
    finally:
        await eng.dispose()


def _factory(engine: AsyncEngine) -> UnitOfWorkFactory:
    return UnitOfWorkFactory(create_session_factory(engine), rls_enabled=True)


async def _seed_org(factory: UnitOfWorkFactory, org_id: UUID) -> None:
    async with factory(tenant_id=None) as uow:
        await uow.session.execute(
            text("INSERT INTO organization (id, slug, name) VALUES (:id, :slug, :name)"),
            {"id": str(org_id), "slug": f"t-{org_id.hex[:16]}", "name": "t"},
        )
        await uow.commit()


def _record(org: UUID, state: str, *, expires_at: datetime) -> OidcLoginStateRecord:
    return OidcLoginStateRecord(
        id=uuid4(),
        organization_id=org,
        state_hash=sha256_hex(state),
        nonce_hash=sha256_hex(f"nonce-{state}"),
        code_verifier=f"verifier-{state}",
        provider="okta",
        redirect_uri="https://gw.example/callback",
        expires_at=expires_at,
    )


async def _save(factory: UnitOfWorkFactory, record: OidcLoginStateRecord) -> None:
    async with factory(tenant_id=record.organization_id) as uow:
        await SqlOidcLoginStateStore(uow.session).save(record)
        await uow.commit()


async def _consume(
    factory: UnitOfWorkFactory, org: UUID, state: str, *, now: datetime = _NOW
) -> OidcLoginStateRecord | None:
    async with factory(tenant_id=org) as uow:
        found = await SqlOidcLoginStateStore(uow.session).consume(sha256_hex(state), now=now)
        await uow.commit()
        return found


async def test_state_is_single_use(engine: AsyncEngine) -> None:
    factory = _factory(engine)
    org, state = uuid4(), f"st-{uuid4().hex}"
    await _seed_org(factory, org)
    await _save(factory, _record(org, state, expires_at=_NOW + _TTL))

    first = await _consume(factory, org, state)
    second = await _consume(factory, org, state)

    assert first is not None
    assert first.code_verifier == f"verifier-{state}"
    assert second is None, "replayed state must not be consumable twice"


async def test_expired_state_is_rejected(engine: AsyncEngine) -> None:
    factory = _factory(engine)
    org, state = uuid4(), f"st-{uuid4().hex}"
    await _seed_org(factory, org)
    # Stored with an expiry already in the past relative to _NOW.
    await _save(factory, _record(org, state, expires_at=_NOW - timedelta(seconds=1)))

    assert await _consume(factory, org, state) is None


async def test_concurrent_callbacks_yield_exactly_one_winner(engine: AsyncEngine) -> None:
    """The race that motivates DELETE ... RETURNING: one success, one replay-detected."""
    factory = _factory(engine)
    org, state = uuid4(), f"st-{uuid4().hex}"
    await _seed_org(factory, org)
    await _save(factory, _record(org, state, expires_at=_NOW + _TTL))

    results = await asyncio.gather(
        _consume(factory, org, state),
        _consume(factory, org, state),
    )

    winners = [r for r in results if r is not None]
    assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"


async def test_other_tenant_cannot_consume_state(engine: AsyncEngine) -> None:
    """RLS: tenant B must not be able to consume tenant A's login state."""
    factory = _factory(engine)
    org_a, org_b, state = uuid4(), uuid4(), f"st-{uuid4().hex}"
    await _seed_org(factory, org_a)
    await _seed_org(factory, org_b)
    await _save(factory, _record(org_a, state, expires_at=_NOW + _TTL))

    assert await _consume(factory, org_b, state) is None, "cross-tenant consume must be blocked"
    assert await _consume(factory, org_a, state) is not None, "owner must still consume it"


async def test_purge_expired_removes_only_stale_rows(engine: AsyncEngine) -> None:
    factory = _factory(engine)
    org = uuid4()
    fresh, stale = f"st-{uuid4().hex}", f"st-{uuid4().hex}"
    await _seed_org(factory, org)
    await _save(factory, _record(org, fresh, expires_at=_NOW + _TTL))
    await _save(factory, _record(org, stale, expires_at=_NOW - timedelta(seconds=1)))

    async with factory(tenant_id=org) as uow:
        removed = await SqlOidcLoginStateStore(uow.session).purge_expired(now=_NOW)
        await uow.commit()

    assert removed >= 1
    assert await _consume(factory, org, fresh) is not None, "sweep must not touch live state"
