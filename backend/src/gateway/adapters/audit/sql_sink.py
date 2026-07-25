"""Durable, hash-chained ``AuthAuditSink`` backed by PostgreSQL (ADR-0009, ADR-0016 Slice 18).

The sink ``composite_sink.py`` was built to receive and ``logging_sink.py`` called "added with the
eventing milestone". It writes the tamper-evident ``audit_event`` log (FR-113/114, NFR-SEC09):
every entry carries ``prev_hash`` and an ``entry_hash`` computed over both, so altering or removing
any entry breaks every subsequent link.

## Tamper-evidence is a chain PLUS a privilege, and both are now real

The chain detects edits; it does not prevent them. Prevention is ``REVOKE UPDATE, DELETE`` from
``app_rw``. Migration 0007 had to extend that revoke - and RLS - to every *partition*, because
neither was inherited when a partition is named directly. Before that migration, ``app_rw`` could
read and rewrite another tenant's audit rows via ``audit_event_2026_07``, which was verified
against real PostgreSQL rather than assumed. The chain here is the second half of a control whose
first half was missing.

## What this sink can and cannot persist, stated rather than implied

``audit_event.organization_id`` is ``NOT NULL`` and RLS-scoped; ``AuthAuditEvent.organization_id``
is optional and is ``None`` for **every authentication rejection**, because a caller whose
credential did not verify has no proven tenant to attribute the event to. Such an event is
therefore **not persisted here** - there is no tenant whose log it belongs in, and no RLS context
under which the row could legally be written. It is still recorded by ``LoggingAuthAuditSink``,
which runs alongside this one in the composite. This is a real limitation of durable
tenant-scoped audit, not an oversight, and widening the schema to admit tenant-less rows would put
unattributable events inside a per-tenant chain.

Two further schema facts are handled by mapping, not by changing the protocol (Rule 5 not
triggered): ``result`` is the four-value ``audit_result`` enum, so the precise
``AuthenticationDecision`` is preserved in ``detail``; and ``actor_type`` is the ``principal_type``
enum, so an unrecognised value becomes NULL rather than failing the write.

## Failure policy: this sink reports, the composite decides

Any database failure raises ``AuditSinkUnavailableError``. That is deliberate and it is *not* a
fail-closed decision made here: ADR-0009 row 7 requires inference-side audit failures to
"buffer+alert" rather than reject, and ``CompositeAuthAuditSink`` already owns exactly that policy
- it logs the failure and lets the remaining sinks run, so authentication is never broken by a
database hiccup. A sink that swallowed its own errors would deny the composite the chance to
alert, which is the difference between a degraded audit trail and a silent one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from gateway.adapters.persistence.audit_tables import audit_chain_head, audit_event
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.domain.auth.models import AuthAuditEvent, AuthenticationDecision, PrincipalType
from gateway.shared.clock import Clock
from gateway.shared.secrets import sha256_bytes

#: ``audit_result`` has four members and none of them can express "invalid_token". Success maps to
#: ``success``; every other decision is a ``failure`` whose precise reason is kept in ``detail``.
_SUCCESS = "success"
_FAILURE = "failure"

#: Field separator for the canonical form. ASCII UNIT SEPARATOR cannot appear in any of the values
#: joined below, so no value can be crafted to look like a field boundary.
_SEP = "\x1f"

_PRINCIPAL_TYPES = frozenset(member.value for member in PrincipalType)


class AuditSinkUnavailableError(RuntimeError):
    """The durable audit log could not be written. Raised for the composite to alert on."""


def _actor_type(raw: str | None) -> str | None:
    """Coerce to a ``principal_type`` member, or NULL. Never raises: an unrecognised actor type
    must not cost us the audit record itself."""
    return raw if raw in _PRINCIPAL_TYPES else None


def chain_entry_hash(
    *,
    prev_hash: bytes | None,
    organization_id: UUID,
    actor_type: str | None,
    actor_id: UUID | None,
    action: str,
    result: str,
    detail: str | None,
    created_at: datetime,
) -> bytes:
    """SHA-256 over the predecessor's digest and this entry's canonical form.

    A pure function, deliberately: the chain rule is the security property, so it is verifiable
    without a database and reusable by any future verifier without re-deriving the field order.

    ``created_at`` is supplied by the caller's clock rather than the database's ``now()`` so that
    the timestamp is *inside* the digest. Hashing over a value the database generates after the
    hash is computed would leave the one field an attacker most wants to move outside the chain.
    """
    canonical = _SEP.join(
        (
            prev_hash.hex() if prev_hash is not None else "",
            str(organization_id),
            actor_type or "",
            str(actor_id) if actor_id is not None else "",
            action,
            result,
            detail or "",
            created_at.isoformat(),
        )
    )
    return sha256_bytes(canonical)


class SqlAuthAuditSink:
    """Appends a hash-chained ``audit_event`` row inside the subject tenant's RLS context."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def record(self, event: AuthAuditEvent) -> None:
        organization_id = event.organization_id
        if organization_id is None:
            # No proven tenant => no tenant-scoped log to append to (see the module docstring).
            # LoggingAuthAuditSink retains it.
            return

        result = _SUCCESS if event.result == AuthenticationDecision.SUCCESS.value else _FAILURE
        created_at = self._clock.now()
        detail: dict[str, Any] = {"decision": event.result}
        if event.detail is not None:
            detail["detail"] = event.detail

        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                session = uow.session
                # Serialise writers for this tenant. Not a row lock: on the very first event
                # there is no audit_chain_head row to lock, so two concurrent writers would both
                # read "no predecessor" and fork the chain - each half individually valid. The
                # lock is transaction-scoped and keyed on this organization only, so tenants
                # never block one another (the Slice-9 ledger uses the same primitive for the
                # same reason).
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
                    {"org": str(organization_id)},
                )

                prev_hash: bytes | None = (
                    await session.execute(
                        select(audit_chain_head.c.entry_hash).where(
                            audit_chain_head.c.organization_id == organization_id
                        )
                    )
                ).scalar_one_or_none()

                entry_hash = chain_entry_hash(
                    prev_hash=prev_hash,
                    organization_id=organization_id,
                    actor_type=_actor_type(event.principal_type),
                    actor_id=event.subject_id,
                    action=event.action,
                    result=result,
                    detail=event.detail,
                    created_at=created_at,
                )

                await session.execute(
                    insert(audit_event).values(
                        id=uuid4(),
                        organization_id=organization_id,
                        actor_type=_actor_type(event.principal_type),
                        actor_id=event.subject_id,
                        action=event.action,
                        result=result,
                        detail=detail,
                        prev_hash=prev_hash,
                        entry_hash=entry_hash,
                        created_at=created_at,
                    )
                )
                await session.execute(
                    pg_insert(audit_chain_head)
                    .values(
                        organization_id=organization_id,
                        entry_hash=entry_hash,
                        updated_at=created_at,
                    )
                    .on_conflict_do_update(
                        index_elements=["organization_id"],
                        set_={"entry_hash": entry_hash, "updated_at": created_at},
                    )
                )
                await uow.commit()
        except (SQLAlchemyError, OSError) as exc:
            # The message is deliberately the exception TYPE only: SQLAlchemy error text can quote
            # bound parameters, and this string reaches a log line (NFR-SEC03).
            raise AuditSinkUnavailableError(type(exc).__name__) from exc
