"""SQLAlchemy Core table definition for the response cache (ADR-0016 Slice 10, ADR-0018).

Points at ``semantic_cache_entry`` - a table ``migrations/sql/0001_initial.sql`` already created,
already RLS-protected (``ENABLE``+``FORCE ROW LEVEL SECURITY`` plus the NULLIF-safe tenant policy
every tenant table shares, see ``0005_rls_nullif_org_guc.sql``) and already granted to ``app_rw``.
No new migration was needed for this slice (see ADR-0018) - unlike Slice 9's ``budget``/
``reservation`` tables, this table's shape does not force fabricating unused catalog data: only the
columns exact-match caching actually uses are declared here (``id``, ``organization_id``,
``request_hash``, ``response``, ``expires_at``); ``project_id``, ``model_id``, ``embedding_id``,
``prompt_fingerprint`` and ``hit_count`` are real, nullable/defaulted columns on the authoritative
table that this slice deliberately leaves untouched rather than populate with data nothing reads
(Rule 5) - the same reasoning ADR-0017 already established for ``org_budget``, applied here to a
table that turned out not to need a narrower replacement.

Kept separate from ``tables.py`` (auth-scoped) and ``ledger_tables.py`` (budget-scoped), matching
the existing one-module-per-capability convention.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, LargeBinary, MetaData, Table, Uuid
from sqlalchemy.dialects.postgresql import JSONB

cache_metadata = MetaData()

semantic_cache_entry = Table(
    "semantic_cache_entry",
    cache_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("request_hash", LargeBinary, nullable=False),
    Column("response", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
)
