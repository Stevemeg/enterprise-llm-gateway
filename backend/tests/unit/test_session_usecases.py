"""Tests for session issue/refresh/logout, incl. refresh reuse detection."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from gateway.application.auth.issue_session import IssueSession
from gateway.application.auth.logout import Logout
from gateway.application.auth.refresh_session import RefreshSession
from gateway.domain.auth.errors import (
    RefreshReuseError,
    SessionRevokedError,
    TokenExpiredError,
    TokenInvalidError,
)
from gateway.shared.clock import Clock
from gateway.shared.secrets import hash_secret
from tests.conftest import FixedClock
from tests.support.auth_fakes import (
    FakeTokenService,
    InMemoryRefreshTokenRepository,
    InMemorySessionRepository,
    RecordingAuditSink,
)

_ACCESS = timedelta(minutes=10)
_REFRESH = timedelta(days=7)
_SESSION = timedelta(days=30)


def _issue_uc(
    sessions: InMemorySessionRepository,
    refresh: InMemoryRefreshTokenRepository,
    tokens: FakeTokenService,
    audit: RecordingAuditSink,
    clock: Clock,
) -> IssueSession:
    return IssueSession(
        sessions,
        refresh,
        tokens,
        audit,
        clock,
        access_ttl=_ACCESS,
        refresh_ttl=_REFRESH,
        session_ttl=_SESSION,
    )


def _refresh_uc(
    sessions: InMemorySessionRepository,
    refresh: InMemoryRefreshTokenRepository,
    tokens: FakeTokenService,
    audit: RecordingAuditSink,
    clock: Clock,
) -> RefreshSession:
    return RefreshSession(
        refresh, sessions, tokens, audit, clock, access_ttl=_ACCESS, refresh_ttl=_REFRESH
    )


async def test_issue_session_creates_session_and_tokens() -> None:
    sessions, refresh, tokens, audit, clock = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
        FixedClock(),
    )
    issued = await _issue_uc(sessions, refresh, tokens, audit, clock)(
        user_id=uuid4(), organization_id=uuid4()
    )
    assert issued.access_token.startswith("access.user.")
    assert issued.refresh_token
    assert len(sessions.sessions) == 1
    assert "session.created" in audit.actions()


async def test_refresh_rotates_and_issues_new_tokens() -> None:
    sessions, refresh, tokens, audit, clock = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
        FixedClock(),
    )
    issued = await _issue_uc(sessions, refresh, tokens, audit, clock)(
        user_id=uuid4(), organization_id=uuid4()
    )
    refreshed = await _refresh_uc(sessions, refresh, tokens, audit, clock)(issued.refresh_token)
    assert refreshed.refresh_token != issued.refresh_token
    assert "session.refreshed" in audit.actions()
    # old token is now marked rotated
    old = refresh.by_hash[hash_secret(issued.refresh_token)]
    assert old.rotated_to is not None


async def test_refresh_reuse_detected_revokes_session() -> None:
    sessions, refresh, tokens, audit, clock = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
        FixedClock(),
    )
    issue = _issue_uc(sessions, refresh, tokens, audit, clock)
    refresh_uc = _refresh_uc(sessions, refresh, tokens, audit, clock)
    issued = await issue(user_id=uuid4(), organization_id=uuid4())
    await refresh_uc(issued.refresh_token)  # legitimate rotation
    with pytest.raises(RefreshReuseError):
        await refresh_uc(issued.refresh_token)  # replay of the rotated token
    assert "refresh.reuse_detected" in audit.actions()
    session_id = next(iter(sessions.sessions))
    assert sessions.sessions[session_id].revoked_at is not None


async def test_unknown_refresh_token_is_rejected() -> None:
    sessions, refresh, tokens, audit, clock = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
        FixedClock(),
    )
    with pytest.raises(TokenInvalidError):
        await _refresh_uc(sessions, refresh, tokens, audit, clock)("never-issued")


async def test_expired_refresh_token_is_rejected() -> None:
    sessions, refresh, tokens, audit = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
    )
    early = FixedClock()
    issued = await _issue_uc(sessions, refresh, tokens, audit, early)(
        user_id=uuid4(), organization_id=uuid4()
    )
    from datetime import UTC, datetime

    class LaterClock:
        def now(self) -> datetime:
            return datetime(2027, 1, 1, tzinfo=UTC)

    with pytest.raises(TokenExpiredError):
        await _refresh_uc(sessions, refresh, tokens, audit, LaterClock())(issued.refresh_token)


async def test_refresh_on_revoked_session_is_rejected() -> None:
    sessions, refresh, tokens, audit, clock = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
        FixedClock(),
    )
    issued = await _issue_uc(sessions, refresh, tokens, audit, clock)(
        user_id=uuid4(), organization_id=uuid4()
    )
    session_id = next(iter(sessions.sessions))
    await Logout(sessions, refresh, audit)(session_id)
    with pytest.raises((SessionRevokedError, RefreshReuseError)):
        await _refresh_uc(sessions, refresh, tokens, audit, clock)(issued.refresh_token)


async def test_logout_revokes_session() -> None:
    sessions, refresh, tokens, audit, clock = (
        InMemorySessionRepository(),
        InMemoryRefreshTokenRepository(),
        FakeTokenService(),
        RecordingAuditSink(),
        FixedClock(),
    )
    await _issue_uc(sessions, refresh, tokens, audit, clock)(
        user_id=uuid4(), organization_id=uuid4()
    )
    session_id = next(iter(sessions.sessions))
    await Logout(sessions, refresh, audit)(session_id)
    assert sessions.sessions[session_id].revoked_at is not None
    assert session_id in refresh.revoked_sessions
    assert "session.logout" in audit.actions()
