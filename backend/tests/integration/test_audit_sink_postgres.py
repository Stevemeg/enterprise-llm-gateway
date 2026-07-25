"""Durable hash-chained audit sink against real PostgreSQL (ADR-0009, ADR-0016 Slice 18).

Runs as ``app_rw`` (ADR-0014), so the append-only and isolation assertions are assertions about
real privileges and real RLS rather than about application-level intent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.audit.sql_sink import (
    AuditSinkUnavailableError,
    SqlAuthAuditSink,
    chain_entry_hash,
)
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.domain.auth.models import AuthAuditEvent
from tests.support.postgres import PG_URL, requires_postgres
from tests.support.rbac import seed_organization

pytestmark = [pytest.mark.integration, requires_postgres]


class SteppingClock:
    """Advances one second per call so entries are distinguishable and ordered."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 7, 25, 9, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


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


def event(org: UUID, action: str = "request.authenticated") -> AuthAuditEvent:
    return AuthAuditEvent(
        action=action,
        result="success",
        organization_id=org,
        principal_type="api_key",
        subject_id=uuid4(),
        detail="api_key",
    )


async def read_chain(factory: UnitOfWorkFactory, org: UUID) -> list[dict[str, Any]]:
    async with factory(tenant_id=org) as uow:
        rows = (
            await uow.session.execute(
                text(
                    "SELECT actor_type, actor_id, action, result, detail, prev_hash, entry_hash, "
                    "created_at FROM audit_event WHERE organization_id = :org "
                    "ORDER BY created_at ASC"
                ),
                {"org": str(org)},
            )
        ).mappings()
        return [dict(row) for row in rows]


# ------------------------------------------------------------------ the chain


async def test_entries_link_and_the_stored_digest_matches_the_rule(
    factory: UnitOfWorkFactory,
) -> None:
    """A verifier must be able to recompute every digest from the stored row and its predecessor.

    This is what makes the chain tamper-*evident* rather than merely tamper-*flavoured*: the test
    performs exactly the verification an auditor would.
    """
    org = uuid4()
    await seed_organization(factory, org)
    sink = SqlAuthAuditSink(factory, SteppingClock())
    for index in range(3):
        await sink.record(event(org, action=f"request.{index}"))

    rows = await read_chain(factory, org)
    assert len(rows) == 3

    previous: bytes | None = None
    for row in rows:
        assert row["prev_hash"] == previous, "each entry must name its predecessor's digest"
        recomputed = chain_entry_hash(
            prev_hash=previous,
            organization_id=org,
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            action=row["action"],
            result=row["result"],
            detail=row["detail"].get("detail"),
            created_at=row["created_at"],
        )
        assert bytes(row["entry_hash"]) == recomputed
        previous = bytes(row["entry_hash"])

    async with factory(tenant_id=org) as uow:
        head = (
            await uow.session.execute(
                text("SELECT entry_hash FROM audit_chain_head WHERE organization_id = :org"),
                {"org": str(org)},
            )
        ).scalar_one()
    assert bytes(head) == previous, "the head must point at the last entry"


async def test_each_tenant_has_its_own_independent_chain(factory: UnitOfWorkFactory) -> None:
    """A global chain would be unverifiable by the only parties RLS lets read it, and one tenant's
    write rate would perturb another's links."""
    org_a, org_b = uuid4(), uuid4()
    for org in (org_a, org_b):
        await seed_organization(factory, org)
    sink = SqlAuthAuditSink(factory, SteppingClock())

    await sink.record(event(org_a))
    await sink.record(event(org_b))
    await sink.record(event(org_a))

    chain_a, chain_b = await read_chain(factory, org_a), await read_chain(factory, org_b)
    assert len(chain_a) == 2
    assert len(chain_b) == 1
    assert chain_a[0]["prev_hash"] is None
    assert chain_b[0]["prev_hash"] is None, "org B's genesis must not chain from org A's entry"
    assert chain_a[1]["prev_hash"] == chain_a[0]["entry_hash"]


async def test_the_precise_decision_survives_the_four_value_result_enum(
    factory: UnitOfWorkFactory,
) -> None:
    """``audit_result`` cannot express "invalid_token", so the decision lives in ``detail``.
    Losing it would make the durable log strictly less informative than the log lines."""
    org = uuid4()
    await seed_organization(factory, org)
    await SqlAuthAuditSink(factory, SteppingClock()).record(
        AuthAuditEvent(
            action="request.rejected",
            result="invalid_token",
            organization_id=org,
            detail="invalid_credential",
        )
    )
    (row,) = await read_chain(factory, org)
    assert row["result"] == "failure"
    assert row["detail"]["decision"] == "invalid_token"
    assert row["detail"]["detail"] == "invalid_credential"


async def test_an_event_far_outside_the_declared_partitions_is_still_recorded(
    factory: UnitOfWorkFactory,
) -> None:
    """0001_initial declared partitions only to 2026-09-01, so the first writer would have begun
    failing with "no partition of relation found". The DEFAULT partition is the catch-all."""
    org = uuid4()
    await seed_organization(factory, org)
    await SqlAuthAuditSink(factory, SteppingClock(datetime(2031, 5, 1, tzinfo=UTC))).record(
        event(org)
    )

    async with factory(tenant_id=org) as uow:
        landed = (
            await uow.session.execute(
                text("SELECT count(*) FROM audit_event_default WHERE organization_id = :org"),
                {"org": str(org)},
            )
        ).scalar_one()
    assert landed == 1


# ------------------------------------------------------------------ immutability


async def _run(factory: UnitOfWorkFactory, org: UUID, statement: str) -> None:
    async with factory(tenant_id=org) as uow:
        await uow.session.execute(text(statement))
        await uow.commit()


@pytest.mark.parametrize("relation", ["audit_event", "audit_event_default"])
@pytest.mark.parametrize("verb", ["UPDATE {} SET action = 'tampered'", "DELETE FROM {}"])
async def test_the_runtime_role_cannot_rewrite_an_audit_entry(
    factory: UnitOfWorkFactory, relation: str, verb: str
) -> None:
    """The chain detects edits; the REVOKE prevents them. Both halves are asserted, and the
    partition is asserted separately because a parent's REVOKE does not reach it."""
    org = uuid4()
    await seed_organization(factory, org)
    await SqlAuthAuditSink(factory, SteppingClock()).record(event(org))

    with pytest.raises(SQLAlchemyError) as caught:
        await _run(factory, org, verb.format(relation))
    assert "permission denied" in str(caught.value).lower()


# ------------------------------------------------------------------ failure policy


async def test_a_database_failure_raises_for_the_composite_to_alert_on() -> None:
    """Deliberately NOT swallowed here: ADR-0009 row 7 puts the buffer+alert decision in the
    composite, and a sink that hid its own failures would deny the composite the chance."""
    unreachable = create_database_engine(url="postgresql+asyncpg://nobody@127.0.0.1:1/none")
    try:
        factory = UnitOfWorkFactory(create_session_factory(unreachable), rls_enabled=True)
        with pytest.raises(AuditSinkUnavailableError) as caught:
            await SqlAuthAuditSink(factory, SteppingClock()).record(event(uuid4()))
        # The TYPE only - SQLAlchemy messages can quote bound parameters (NFR-SEC03).
        assert "@" not in str(caught.value)
        assert "127.0.0.1" not in str(caught.value)
    finally:
        await unreachable.dispose()
