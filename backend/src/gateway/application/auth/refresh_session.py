"""Refresh an access token by rotating the refresh token (Auth §6, ADR-0008).

Rotation + **reuse detection**: presenting a rotated/revoked refresh token is treated as
theft — the whole session's tokens are revoked and an audit event is emitted. Expired
refresh tokens and revoked sessions are rejected.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from gateway.application.ports.auth import (
    AuthAuditSink,
    RefreshTokenRepository,
    SessionRepository,
    TokenService,
)
from gateway.domain.auth.errors import (
    RefreshReuseError,
    SessionRevokedError,
    TokenExpiredError,
    TokenInvalidError,
)
from gateway.domain.auth.models import (
    AuthAuditEvent,
    IssuedTokens,
    Principal,
    PrincipalType,
    RefreshTokenRecord,
)
from gateway.shared.clock import Clock
from gateway.shared.secrets import generate_token, hash_secret


class RefreshSession:
    def __init__(
        self,
        refresh_tokens: RefreshTokenRepository,
        sessions: SessionRepository,
        token_service: TokenService,
        audit: AuthAuditSink,
        clock: Clock,
        *,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
    ) -> None:
        self._refresh = refresh_tokens
        self._sessions = sessions
        self._token_service = token_service
        self._audit = audit
        self._clock = clock
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl

    async def __call__(self, presented_refresh: str) -> IssuedTokens:
        record = await self._refresh.get_by_hash(hash_secret(presented_refresh))
        if record is None:
            raise TokenInvalidError("unknown refresh token")

        # Reuse detection: a rotated/revoked token means a stolen copy was replayed.
        if record.rotated_to is not None or record.revoked_at is not None:
            await self._refresh.revoke_session_tokens(record.session_id)
            await self._sessions.revoke(record.session_id)
            await self._audit.record(
                AuthAuditEvent(
                    action="refresh.reuse_detected",
                    result="failure",
                    organization_id=record.organization_id,
                    detail="rotated or revoked refresh token replayed; session revoked",
                )
            )
            raise RefreshReuseError("refresh token reuse detected")

        now = self._clock.now()
        if now > record.expires_at:
            raise TokenExpiredError("refresh token expired")

        session = await self._sessions.get(record.session_id)
        if session is None or session.revoked_at is not None or now > session.expires_at:
            raise SessionRevokedError("session is no longer active")

        new_secret = generate_token()
        new_id = uuid4()
        await self._refresh.add(
            RefreshTokenRecord(
                id=new_id,
                session_id=record.session_id,
                organization_id=record.organization_id,
                token_hash=hash_secret(new_secret),
                expires_at=now + self._refresh_ttl,
            )
        )
        await self._refresh.mark_rotated(record.id, new_id)

        principal = Principal(
            principal_type=PrincipalType.USER,
            subject_id=session.user_id,
            organization_id=session.organization_id,
        )
        access = self._token_service.issue_access_token(principal=principal, ttl=self._access_ttl)
        await self._audit.record(
            AuthAuditEvent(
                action="session.refreshed",
                result="success",
                organization_id=session.organization_id,
                principal_type=PrincipalType.USER.value,
                subject_id=session.user_id,
            )
        )
        return IssuedTokens(access_token=access, refresh_token=new_secret)
