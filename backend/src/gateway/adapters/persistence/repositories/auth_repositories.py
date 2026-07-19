"""SQLAlchemy authentication repositories (ADR-0002/0008/0013).

Implement the application ports against the auth tables using SQLAlchemy Core, within the
UoW's session. Rows map to framework-free domain records; ``bytea`` hashes are converted
to/from hex so the domain layer never handles raw bytes. Revocation timestamps come from an
injected clock (deterministic + testable).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.adapters.persistence import tables as t
from gateway.domain.auth.models import (
    ApiKeyRecord,
    ApiKeyStatus,
    OAuthIdentityRecord,
    OidcLoginStateRecord,
    RefreshTokenRecord,
    ServiceAccountCredentialRecord,
    SessionRecord,
)
from gateway.shared.clock import Clock


def _to_bytes(hex_hash: str) -> bytes:
    return bytes.fromhex(hex_hash)


def _to_hex(value: bytes) -> str:
    return bytes(value).hex()


class SqlApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        row = (
            (await self._session.execute(select(t.api_key).where(t.api_key.c.key_prefix == prefix)))
            .mappings()
            .first()
        )
        if row is None:
            return None
        scopes = (
            (
                await self._session.execute(
                    select(t.api_key_scope.c.scope).where(t.api_key_scope.c.api_key_id == row["id"])
                )
            )
            .scalars()
            .all()
        )
        return ApiKeyRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            key_hash=_to_hex(row["key_hash"]),
            scopes=tuple(scopes),
            is_active=row["status"] == ApiKeyStatus.ACTIVE,
            expires_at=row["expires_at"],
        )


class SqlServiceAccountCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: ServiceAccountCredentialRecord) -> None:
        await self._session.execute(
            insert(t.service_account_credential).values(
                id=record.id,
                organization_id=record.organization_id,
                service_account_id=record.service_account_id,
                client_id=record.client_id,
                secret_hash=_to_bytes(record.secret_hash),
                status=ApiKeyStatus(record.status),
                expires_at=record.expires_at,
            )
        )

    async def get_by_client_id(self, client_id: str) -> ServiceAccountCredentialRecord | None:
        row = (
            (
                await self._session.execute(
                    select(t.service_account_credential).where(
                        t.service_account_credential.c.client_id == client_id
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return ServiceAccountCredentialRecord(
            id=row["id"],
            service_account_id=row["service_account_id"],
            organization_id=row["organization_id"],
            client_id=row["client_id"],
            secret_hash=_to_hex(row["secret_hash"]),
            status=row["status"],
            expires_at=row["expires_at"],
        )

    async def revoke(self, credential_id: UUID) -> None:
        await self._session.execute(
            update(t.service_account_credential)
            .where(t.service_account_credential.c.id == credential_id)
            .values(status=ApiKeyStatus.REVOKED)
        )


class SqlSessionRepository:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def add(self, record: SessionRecord) -> None:
        await self._session.execute(
            insert(t.session_table).values(
                id=record.id,
                organization_id=record.organization_id,
                user_id=record.user_id,
                created_at=record.created_at,
                expires_at=record.expires_at,
                revoked_at=record.revoked_at,
            )
        )

    async def get(self, session_id: UUID) -> SessionRecord | None:
        row = (
            (
                await self._session.execute(
                    select(t.session_table).where(t.session_table.c.id == session_id)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return SessionRecord(
            id=row["id"],
            user_id=row["user_id"],
            organization_id=row["organization_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    async def revoke(self, session_id: UUID) -> None:
        await self._session.execute(
            update(t.session_table)
            .where(t.session_table.c.id == session_id)
            .values(revoked_at=self._clock.now())
        )


class SqlRefreshTokenRepository:
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def add(self, record: RefreshTokenRecord) -> None:
        await self._session.execute(
            insert(t.refresh_token).values(
                id=record.id,
                organization_id=record.organization_id,
                session_id=record.session_id,
                token_hash=_to_bytes(record.token_hash),
                expires_at=record.expires_at,
                rotated_to=record.rotated_to,
                revoked_at=record.revoked_at,
            )
        )

    async def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        row = (
            (
                await self._session.execute(
                    select(t.refresh_token).where(
                        t.refresh_token.c.token_hash == _to_bytes(token_hash)
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return RefreshTokenRecord(
            id=row["id"],
            session_id=row["session_id"],
            organization_id=row["organization_id"],
            token_hash=_to_hex(row["token_hash"]),
            expires_at=row["expires_at"],
            rotated_to=row["rotated_to"],
            revoked_at=row["revoked_at"],
        )

    async def mark_rotated(self, token_id: UUID, rotated_to: UUID) -> None:
        await self._session.execute(
            update(t.refresh_token)
            .where(t.refresh_token.c.id == token_id)
            .values(rotated_to=rotated_to)
        )

    async def revoke_session_tokens(self, session_id: UUID) -> None:
        await self._session.execute(
            update(t.refresh_token)
            .where(t.refresh_token.c.session_id == session_id)
            .values(revoked_at=self._clock.now())
        )


class SqlOAuthIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: OAuthIdentityRecord) -> None:
        await self._session.execute(
            insert(t.oauth_identity).values(
                id=record.id,
                organization_id=record.organization_id,
                user_id=record.user_id,
                provider=record.provider,
                subject=record.subject,
            )
        )

    async def get_by_subject(self, provider: str, subject: str) -> OAuthIdentityRecord | None:
        row = (
            (
                await self._session.execute(
                    select(t.oauth_identity).where(
                        t.oauth_identity.c.provider == provider,
                        t.oauth_identity.c.subject == subject,
                    )
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return OAuthIdentityRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            user_id=row["user_id"],
            provider=row["provider"],
            subject=row["subject"],
        )


class SqlOidcLoginStateStore:
    """OIDC login-state store with **atomic single-use consume** (ADR-0015).

    ``consume`` issues ``DELETE ... RETURNING`` so exactly one of N concurrent callbacks
    presenting the same ``state`` receives the record; the losers match nothing and get
    ``None`` (replay detected). This closes the check-to-use window a SELECT-then-UPDATE or
    a cache flag would leave open. Expired records are treated as absent (fail closed) even
    though the row is still deleted, so a stale state can never complete a login.

    All queries run inside the tenant-scoped UoW, so RLS confines them to one organization.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, record: OidcLoginStateRecord) -> None:
        await self._session.execute(
            insert(t.oidc_login_state).values(
                id=record.id,
                organization_id=record.organization_id,
                state_hash=_to_bytes(record.state_hash),
                nonce_hash=_to_bytes(record.nonce_hash),
                code_verifier=record.code_verifier,
                code_challenge_method=record.code_challenge_method,
                provider=record.provider,
                redirect_uri=record.redirect_uri,
                return_to=record.return_to,
                expires_at=record.expires_at,
            )
        )

    async def consume(self, state_hash: str, *, now: datetime) -> OidcLoginStateRecord | None:
        row = (
            (
                await self._session.execute(
                    delete(t.oidc_login_state)
                    .where(t.oidc_login_state.c.state_hash == _to_bytes(state_hash))
                    .returning(*t.oidc_login_state.c)
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None  # unknown or already consumed (replay)
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now:
            return None  # expired ⇒ fail closed (row is consumed regardless)
        return OidcLoginStateRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            state_hash=_to_hex(row["state_hash"]),
            nonce_hash=_to_hex(row["nonce_hash"]),
            code_verifier=row["code_verifier"],
            code_challenge_method=row["code_challenge_method"],
            provider=row["provider"],
            redirect_uri=row["redirect_uri"],
            return_to=row["return_to"],
            expires_at=expires_at,
        )

    async def purge_expired(self, *, now: datetime) -> int:
        """Hygiene sweep (ADR-0015): correctness never depends on this having run."""
        result = await self._session.execute(
            delete(t.oidc_login_state).where(t.oidc_login_state.c.expires_at <= now)
        )
        # execute() is typed Result[Any]; a DELETE always yields a CursorResult with rowcount.
        return int(cast("CursorResult[Any]", result).rowcount or 0)
