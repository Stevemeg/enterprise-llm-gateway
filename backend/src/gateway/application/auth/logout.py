"""Revoke a session and all its refresh tokens (Authentication_Architecture.md §12)."""

from __future__ import annotations

from uuid import UUID

from gateway.application.ports.auth import AuthAuditSink, RefreshTokenRepository, SessionRepository
from gateway.domain.auth.models import AuthAuditEvent


class Logout:
    def __init__(
        self,
        sessions: SessionRepository,
        refresh_tokens: RefreshTokenRepository,
        audit: AuthAuditSink,
    ) -> None:
        self._sessions = sessions
        self._refresh = refresh_tokens
        self._audit = audit

    async def __call__(self, session_id: UUID) -> None:
        await self._sessions.revoke(session_id)
        await self._refresh.revoke_session_tokens(session_id)
        await self._audit.record(AuthAuditEvent(action="session.logout", result="success"))
