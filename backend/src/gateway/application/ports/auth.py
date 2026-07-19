"""Authentication ports (Backend_Implementation_Guide.md §6/§9).

Framework-free interfaces the auth use-cases depend on. Concrete implementations
(SQLAlchemy repositories, the JWT-backed token service, the audit sink) are adapters
wired in the composition root. JWT lives behind ``TokenService`` so the application never
imports the crypto library (import-linter enforced).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from gateway.domain.auth.models import (
    ApiKeyRecord,
    AuthAuditEvent,
    OAuthIdentityRecord,
    OidcLoginStateRecord,
    Principal,
    RefreshTokenRecord,
    ServiceAccountCredentialRecord,
    ServiceAccountRecord,
    SessionRecord,
)


class ApiKeyRepository(Protocol):
    async def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None: ...


class ServiceAccountRepository(Protocol):
    async def get_by_client_id(self, client_id: str) -> ServiceAccountRecord | None: ...


class ServiceAccountCredentialRepository(Protocol):
    async def add(self, record: ServiceAccountCredentialRecord) -> None: ...
    async def get_by_client_id(self, client_id: str) -> ServiceAccountCredentialRecord | None: ...
    async def revoke(self, credential_id: UUID) -> None: ...


class OAuthIdentityRepository(Protocol):
    async def get_by_subject(self, provider: str, subject: str) -> OAuthIdentityRecord | None: ...
    async def add(self, record: OAuthIdentityRecord) -> None: ...


class OidcLoginStateStore(Protocol):
    """Single-use, TTL-bounded store for OIDC login state (ADR-0015).

    ``consume`` MUST be atomic: exactly one concurrent caller may receive a given record
    (the Postgres adapter uses ``DELETE ... RETURNING``). An expired record is treated as
    absent — callers fail closed. The port keeps the backing store swappable (Redis later)
    without touching the OIDC use-cases.
    """

    async def save(self, record: OidcLoginStateRecord) -> None: ...

    async def consume(self, state_hash: str, *, now: datetime) -> OidcLoginStateRecord | None:
        """Atomically consume the record for ``state_hash``; ``None`` if absent/expired/replayed."""
        ...

    async def purge_expired(self, *, now: datetime) -> int:
        """Delete records past their TTL; returns how many were removed (hygiene sweep)."""
        ...


class SessionRepository(Protocol):
    async def add(self, record: SessionRecord) -> None: ...
    async def get(self, session_id: UUID) -> SessionRecord | None: ...
    async def revoke(self, session_id: UUID) -> None: ...


class RefreshTokenRepository(Protocol):
    async def add(self, record: RefreshTokenRecord) -> None: ...
    async def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None: ...
    async def mark_rotated(self, token_id: UUID, rotated_to: UUID) -> None: ...
    async def revoke_session_tokens(self, session_id: UUID) -> None: ...


class TokenService(Protocol):
    """Issues gateway access tokens (JWT adapter implements this)."""

    def issue_access_token(self, *, principal: Principal, ttl: timedelta) -> str: ...


class AuthAuditSink(Protocol):
    async def record(self, event: AuthAuditEvent) -> None: ...


class AccessTokenVerifier(Protocol):
    """Validates a gateway access token and returns the authenticated principal."""

    def verify(self, token: str) -> Principal: ...


class Authenticator(Protocol):
    """Resolves a bearer credential (API key or JWT) to a principal (fail closed)."""

    async def authenticate(self, credential: str) -> Principal: ...
