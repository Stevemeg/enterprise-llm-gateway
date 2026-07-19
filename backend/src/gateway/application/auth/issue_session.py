"""Create a login session and issue access + refresh tokens (Auth §6/§12).

Called after a verified login (e.g., OIDC). Persists a session and the first refresh
token (hashed), returns the access token and the one-time refresh secret.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from gateway.application.ports.auth import (
    AuthAuditSink,
    RefreshTokenRepository,
    SessionRepository,
    TokenService,
)
from gateway.domain.auth.models import (
    AuthAuditEvent,
    IssuedTokens,
    Principal,
    PrincipalType,
    RefreshTokenRecord,
    SessionRecord,
)
from gateway.shared.clock import Clock
from gateway.shared.secrets import generate_token, hash_secret


class IssueSession:
    def __init__(
        self,
        sessions: SessionRepository,
        refresh_tokens: RefreshTokenRepository,
        token_service: TokenService,
        audit: AuthAuditSink,
        clock: Clock,
        *,
        access_ttl: timedelta,
        refresh_ttl: timedelta,
        session_ttl: timedelta,
    ) -> None:
        self._sessions = sessions
        self._refresh = refresh_tokens
        self._token_service = token_service
        self._audit = audit
        self._clock = clock
        self._access_ttl = access_ttl
        self._refresh_ttl = refresh_ttl
        self._session_ttl = session_ttl

    async def __call__(self, *, user_id: UUID, organization_id: UUID) -> IssuedTokens:
        now = self._clock.now()
        session = SessionRecord(
            id=uuid4(),
            user_id=user_id,
            organization_id=organization_id,
            created_at=now,
            expires_at=now + self._session_ttl,
        )
        await self._sessions.add(session)

        refresh_secret = generate_token()
        await self._refresh.add(
            RefreshTokenRecord(
                id=uuid4(),
                session_id=session.id,
                organization_id=organization_id,
                token_hash=hash_secret(refresh_secret),
                expires_at=now + self._refresh_ttl,
            )
        )
        principal = Principal(
            principal_type=PrincipalType.USER,
            subject_id=user_id,
            organization_id=organization_id,
        )
        access = self._token_service.issue_access_token(principal=principal, ttl=self._access_ttl)
        await self._audit.record(
            AuthAuditEvent(
                action="session.created",
                result="success",
                organization_id=organization_id,
                principal_type=PrincipalType.USER.value,
                subject_id=user_id,
            )
        )
        return IssuedTokens(access_token=access, refresh_token=refresh_secret)
