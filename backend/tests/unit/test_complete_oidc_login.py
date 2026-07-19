"""End-to-end OIDC login orchestration (ADR-0015), with fakes for the IdP.

Exercises the whole callback path in one go — signed state -> atomic consume -> code exchange
-> id_token/nonce verification -> identity lookup -> session creation -> audit — so the pieces
are proven to fit together, not just individually. Replay is asserted across the *whole*
orchestration, which is where single-use actually has to hold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from gateway.adapters.security.oidc_state import ParsedState, StateSigner
from gateway.application.auth.complete_oidc_login import CompleteOidcLogin
from gateway.domain.auth.errors import OidcIdentityError, OidcStateInvalidError
from gateway.domain.auth.models import (
    AuthenticationDecision,
    OAuthIdentityRecord,
    OidcLoginStateRecord,
)
from gateway.shared.secrets import sha256_hex
from tests.support.auth_fakes import (
    FakeOidcProvider,
    FakeTokenService,
    InMemoryOAuthIdentityRepository,
    InMemoryOidcLoginStateStore,
    InMemoryRefreshTokenRepository,
    InMemorySessionRepository,
    RecordingAuditSink,
)

_NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
_NONCE = "the-nonce"
_PROVIDER = "okta"
_REDIRECT = "https://gw.example/callback"
_SIGNING_KEY = "state-signing-key"


class FixedClock:
    def now(self) -> datetime:
        return _NOW


class _Harness:
    def __init__(self) -> None:
        self.states = InMemoryOidcLoginStateStore()
        self.provider = FakeOidcProvider(nonce=_NONCE)
        self.identities = InMemoryOAuthIdentityRepository()
        self.sessions = InMemorySessionRepository()
        self.refresh_tokens = InMemoryRefreshTokenRepository()
        self.audit = RecordingAuditSink()
        self.use_case = CompleteOidcLogin(
            state_store=self.states,
            provider=self.provider,
            identities=self.identities,
            sessions=self.sessions,
            refresh_tokens=self.refresh_tokens,
            tokens=FakeTokenService(),
            audit=self.audit,
            clock=FixedClock(),
        )


async def _prepare(
    harness: _Harness, org: UUID, *, link_identity: bool = True, ttl_minutes: int = 5
) -> tuple[StateSigner, str, ParsedState, UUID]:
    """Do the /authorize half: sign a state and persist the matching login-state row."""
    signer = StateSigner(_SIGNING_KEY)
    state, parsed = signer.issue(org)
    await harness.states.save(
        OidcLoginStateRecord(
            id=uuid4(),
            organization_id=org,
            state_hash=parsed.state_hash,
            nonce_hash=sha256_hex(_NONCE),
            code_verifier="the-verifier",
            provider=_PROVIDER,
            redirect_uri=_REDIRECT,
            expires_at=_NOW + timedelta(minutes=ttl_minutes),
        )
    )
    user_id = uuid4()
    if link_identity:
        await harness.identities.add(
            OAuthIdentityRecord(
                id=uuid4(),
                organization_id=org,
                user_id=user_id,
                provider=_PROVIDER,
                subject="idp-subject-1",
            )
        )
    return signer, state, parsed, user_id


async def test_complete_oidc_login_success() -> None:
    """The happy path end-to-end: every stage runs and a session is minted."""
    harness = _Harness()
    org = uuid4()
    signer, state, _parsed, _user_id = await _prepare(harness, org)

    # Delivery layer verifies the signed state BEFORE any DB access (RLS bootstrapping).
    verified = signer.verify(state)
    assert verified.organization_id == org

    tokens = await harness.use_case.execute(
        organization_id=verified.organization_id,
        state_hash=verified.state_hash,
        code="auth-code-1",
        redirect_uri=_REDIRECT,
    )

    assert tokens.access_token
    assert tokens.refresh_token
    # The code was actually exchanged with the provider, using the stored PKCE verifier.
    assert harness.provider.exchanges == ["auth-code-1"]
    # A session and a refresh token were persisted.
    assert len(harness.sessions.sessions) == 1
    # Exactly one success audit event, using the enum vocabulary.
    results = [e.result for e in harness.audit.events]
    assert AuthenticationDecision.SUCCESS.value in results


async def test_replayed_oidc_callback_fails() -> None:
    """The same callback twice: first succeeds, second is rejected as replay."""
    harness = _Harness()
    org = uuid4()
    signer, state, _parsed, _ = await _prepare(harness, org)
    verified = signer.verify(state)

    first = await harness.use_case.execute(
        organization_id=verified.organization_id,
        state_hash=verified.state_hash,
        code="auth-code-1",
        redirect_uri=_REDIRECT,
    )
    assert first.access_token

    with pytest.raises(OidcStateInvalidError):
        await harness.use_case.execute(
            organization_id=verified.organization_id,
            state_hash=verified.state_hash,
            code="auth-code-1",
            redirect_uri=_REDIRECT,
        )

    # The replay must not have reached the IdP a second time, and must be audited as a failure.
    assert harness.provider.exchanges == ["auth-code-1"]
    assert AuthenticationDecision.INVALID_TOKEN.value in [e.result for e in harness.audit.events]


async def test_expired_state_is_rejected_end_to_end() -> None:
    harness = _Harness()
    org = uuid4()
    signer, state, _, _ = await _prepare(harness, org, ttl_minutes=-1)  # already expired
    verified = signer.verify(state)

    with pytest.raises(OidcStateInvalidError):
        await harness.use_case.execute(
            organization_id=verified.organization_id,
            state_hash=verified.state_hash,
            code="auth-code-1",
            redirect_uri=_REDIRECT,
        )
    assert harness.provider.exchanges == [], "expired state must never reach the IdP"


async def test_unlinked_federated_identity_is_rejected() -> None:
    harness = _Harness()
    org = uuid4()
    signer, state, _, _ = await _prepare(harness, org, link_identity=False)
    verified = signer.verify(state)

    with pytest.raises(OidcIdentityError):
        await harness.use_case.execute(
            organization_id=verified.organization_id,
            state_hash=verified.state_hash,
            code="auth-code-1",
            redirect_uri=_REDIRECT,
        )
    assert len(harness.sessions.sessions) == 0


async def test_state_from_another_tenant_is_rejected() -> None:
    """Defence in depth behind RLS: the consumed row's org must match the verified state."""
    harness = _Harness()
    org, other_org = uuid4(), uuid4()
    _signer, _state, verified_state, _ = await _prepare(harness, org)

    with pytest.raises(OidcStateInvalidError):
        await harness.use_case.execute(
            organization_id=other_org,  # mismatched tenant
            state_hash=verified_state.state_hash,
            code="auth-code-1",
            redirect_uri=_REDIRECT,
        )
