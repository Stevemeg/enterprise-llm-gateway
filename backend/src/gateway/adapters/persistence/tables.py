"""SQLAlchemy Core table definitions for the authentication tables.

These describe the columns the repositories query; the **authoritative DDL is Schema.sql /
Alembic** (which owns constraints, RLS, enums). Portable types (``Uuid``, ``LargeBinary``,
``DateTime(timezone=True)``) let the same definitions run against PostgreSQL (production) and
SQLite (local integration tests). Foreign keys are intentionally omitted here — they are enforced
by the database schema, not this query interface. Kept in sync with Schema.sql (CI drift check).
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Enum, LargeBinary, MetaData, String, Table, Text, Uuid

from gateway.domain.auth.models import ApiKeyStatus

auth_metadata = MetaData()

# Bound to the *existing* PostgreSQL ENUM ``api_key_status`` (owned by Schema.sql/Alembic, never
# created from here). Declaring these columns as String made asyncpg send text where an enum was
# expected, which PostgreSQL rejects outright. ``values_callable`` persists the member *values*
# ('active', ...) rather than names; on SQLite this degrades to VARCHAR for local integration tests.
_API_KEY_STATUS = Enum(
    ApiKeyStatus,
    name="api_key_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
    create_constraint=False,
)

api_key = Table(
    "api_key",
    auth_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("project_id", Uuid),
    Column("name", Text, nullable=False),
    Column("key_prefix", Text, nullable=False),
    Column("key_hash", LargeBinary, nullable=False),
    Column("status", _API_KEY_STATUS, nullable=False),
    Column("created_by", Uuid),
    Column("last_used_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

api_key_scope = Table(
    "api_key_scope",
    auth_metadata,
    Column("api_key_id", Uuid, primary_key=True),
    Column("scope", String, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
)

service_account_credential = Table(
    "service_account_credential",
    auth_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("service_account_id", Uuid, nullable=False),
    Column("client_id", Text, nullable=False),
    Column("secret_hash", LargeBinary, nullable=False),
    Column("status", _API_KEY_STATUS, nullable=False),
    Column("rotation_reason", Text),
    Column("created_by", Uuid),
    Column("revoked_by", Uuid),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("last_used_at", DateTime(timezone=True)),
    Column("last_rotated_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)

session_table = Table(
    "session",
    auth_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("user_id", Uuid, nullable=False),
    Column("ip_address", String),
    Column("user_agent", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)

refresh_token = Table(
    "refresh_token",
    auth_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("session_id", Uuid, nullable=False),
    Column("token_hash", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("rotated_to", Uuid),
    Column("revoked_at", DateTime(timezone=True)),
)

oauth_identity = Table(
    "oauth_identity",
    auth_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("user_id", Uuid, nullable=False),
    Column("provider", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

oidc_login_state = Table(
    "oidc_login_state",
    auth_metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, nullable=False),
    Column("state_hash", LargeBinary, nullable=False),
    Column("nonce_hash", LargeBinary, nullable=False),
    Column("code_verifier", Text, nullable=False),
    Column("code_challenge_method", Text, nullable=False),
    Column("provider", Text, nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("return_to", Text),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)
