"""Hash-chain and audit-sink unit tests (ADR-0016 Slice 18, ADR-0009).

The chain rule is the security property, so it is tested as a pure function first - a chain that
is only exercised through a database is a chain whose rule nobody ever stated. The database-backed
behaviour is in ``tests/integration/test_audit_sink_postgres.py``.

Failure-first: every path that could plausibly end in "a tampered entry still verifies" is
asserted before any happy path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from gateway.adapters.audit.composite_sink import CompositeAuthAuditSink
from gateway.adapters.audit.sql_sink import (
    AuditSinkUnavailableError,
    SqlAuthAuditSink,
    _actor_type,
    chain_entry_hash,
)
from gateway.domain.auth.models import AuthAuditEvent

ORG = uuid4()
ACTOR = uuid4()
MOMENT = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def entry(**overrides: object) -> bytes:
    base: dict[str, object] = {
        "prev_hash": None,
        "organization_id": ORG,
        "actor_type": "user",
        "actor_id": ACTOR,
        "action": "request.authenticated",
        "result": "success",
        "detail": "jwt",
        "created_at": MOMENT,
    }
    base.update(overrides)
    return chain_entry_hash(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------ tamper detection (first)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", uuid4()),
        ("actor_type", "api_key"),
        ("actor_id", uuid4()),
        ("action", "request.rejected"),
        ("result", "failure"),
        ("detail", "api_key"),
        ("created_at", datetime(2026, 7, 25, 12, 0, 1, tzinfo=UTC)),
    ],
)
def test_changing_any_audited_field_changes_the_digest(field: str, value: object) -> None:
    """Every field that is audited must be inside the digest, or it can be edited undetectably."""
    assert entry() != entry(**{field: value})


def test_changing_the_predecessor_changes_the_digest() -> None:
    """The chain link itself: re-parenting an entry must be detectable."""
    assert entry(prev_hash=b"\x01" * 32) != entry(prev_hash=b"\x02" * 32)
    assert entry(prev_hash=None) != entry(prev_hash=b"\x00" * 32)


def test_field_values_cannot_be_shifted_across_the_separator() -> None:
    """A canonical form joined by a character that can appear in a value would let two different
    entries collide - e.g. action='a' detail='b' vs action='a|b' detail=''."""
    assert entry(action="a", detail="b") != entry(action="a\x1fb", detail="")


def test_the_digest_is_deterministic_and_full_length() -> None:
    assert entry() == entry()
    assert len(entry()) == 32


# ------------------------------------------------------------------ enum coercion


@pytest.mark.parametrize("raw", ["user", "service_account", "api_key"])
def test_known_principal_types_are_preserved(raw: str) -> None:
    assert _actor_type(raw) == raw


@pytest.mark.parametrize("raw", [None, "", "robot", "USER", "admin"])
def test_an_unrecognised_actor_type_becomes_null_rather_than_failing_the_write(
    raw: str | None,
) -> None:
    """``actor_type`` is a PostgreSQL enum. Losing the whole audit record because one optional
    descriptive column had an unexpected value would be the wrong trade."""
    assert _actor_type(raw) is None


# ------------------------------------------------------------------ the org-less event


class _ExplodingFactory:
    """Any use at all is a failure - proves the sink never opened a unit of work."""

    def __call__(self, **_: object) -> object:
        raise AssertionError("the sink must not open a unit of work for a tenant-less event")


async def test_an_event_without_an_organization_is_not_persisted_and_touches_no_database() -> None:
    """A rejected credential has no proven tenant, so there is no tenant-scoped log to append to.

    Asserted by side effect, not just by return value: the factory raises if it is called at all.
    """
    sink = SqlAuthAuditSink(_ExplodingFactory(), FixedMoment())  # type: ignore[arg-type]
    await sink.record(AuthAuditEvent(action="request.rejected", result="invalid_token"))


class FixedMoment:
    def now(self) -> datetime:
        return MOMENT


# ------------------------------------------------------------------ failure policy


class _FailingSink:
    def __init__(self) -> None:
        self.calls = 0

    async def record(self, event: AuthAuditEvent) -> None:
        self.calls += 1
        raise AuditSinkUnavailableError("OperationalError")


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuthAuditEvent] = []

    async def record(self, event: AuthAuditEvent) -> None:
        self.events.append(event)


async def test_a_failing_durable_sink_does_not_stop_the_other_sinks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ADR-0009 row 7: inference-side audit failures buffer+alert, they do not reject.

    Before Slice 18 the composite had only ever held ONE sink, so this isolation path had never
    executed. The durable sink is the second one, which is what makes it reachable.
    """
    failing, surviving = _FailingSink(), _RecordingSink()
    event = AuthAuditEvent(action="request.authenticated", result="success", organization_id=ORG)

    await CompositeAuthAuditSink([failing, surviving]).record(event)

    assert failing.calls == 1
    assert surviving.events == [event], "a sink failure must not swallow the record for the others"


async def test_the_composite_never_propagates_a_sink_failure_to_its_caller() -> None:
    """Authentication must not break because a log shipper hiccuped."""
    await CompositeAuthAuditSink([_FailingSink()]).record(
        AuthAuditEvent(action="request.authenticated", result="success", organization_id=ORG)
    )
