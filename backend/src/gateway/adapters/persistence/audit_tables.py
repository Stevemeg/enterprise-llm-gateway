"""SQLAlchemy Core table definitions for the audit log (ADR-0009, ADR-0016 Slice 18).

``audit_event`` is the Phase-1 append-only, hash-chained, RANGE-partitioned log; the application
may only ``INSERT`` into it (``UPDATE``/``DELETE`` are revoked from ``app_rw`` on the parent *and*,
since migration 0007, on every partition). ``audit_chain_head`` is the authoritative per-tenant
chain head introduced by Slice 18.

``prev_hash``/``entry_hash`` are ``bytea``: raw digests, not hex. The sink converts at this
boundary so the rest of the code never handles encoding decisions.

``detail`` is ``jsonb``. It is bound as ``JSONB`` rather than ``Text`` so a Python mapping travels
as JSON without the adapter hand-serialising it - and so the column keeps the shape Schema.sql
promises rather than quietly becoming a string field holding JSON.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, LargeBinary, MetaData, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

audit_metadata = MetaData()

#: Bound to the existing PostgreSQL ENUMs (owned by 0001_initial.sql, never created from here).
_PRINCIPAL_TYPE = Enum(
    "user",
    "service_account",
    "api_key",
    name="principal_type",
    create_type=False,
)

_AUDIT_RESULT = Enum(
    "allow",
    "deny",
    "success",
    "failure",
    name="audit_result",
    create_type=False,
)

audit_event = Table(
    "audit_event",
    audit_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("actor_type", _PRINCIPAL_TYPE),
    Column("actor_id", Uuid),
    Column("action", Text, nullable=False),
    Column("result", _AUDIT_RESULT, nullable=False),
    Column("detail", JSONB, nullable=False),
    Column("prev_hash", LargeBinary),
    Column("entry_hash", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

audit_chain_head = Table(
    "audit_chain_head",
    audit_metadata,
    Column("organization_id", Uuid, primary_key=True),
    Column("entry_hash", LargeBinary, nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)
