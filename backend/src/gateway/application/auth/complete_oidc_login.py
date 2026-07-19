"""Complete an OIDC login from the /callback request (ADR-0015, Auth §7).

Orchestration only — no HTTP, no crypto, no SQL. The order of operations *is* the security
property, so it is fixed and deliberate:

    1. verify the signed ``state`` (HMAC) ....... nothing is trusted before this
    2. resolve the tenant from the verified state and bind the RLS context
    3. atomically consume the state row ......... single-use; replay loses the race
    4. exchange the code + PKCE verifier ........ IdP call, bounded timeouts, no retries
    5. verify the id_token (sig/iss/aud/exp) and bind the ``nonce`` to the consumed state
    6. resolve the federated identity to a local user
    7. mint a session + tokens
    8. audit the outcome

Any failure short-circuits, is audited with an ``AuthenticationDecision``, and raises — there
is no partial login (ADR-0009 fail closed).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from gateway.application.ports.auth import (
    AuthAuditSink,
    OAuthIdentityRepository,
    OidcLoginStateStore,
    RefreshTokenRepository,
    SessionRepository,
    TokenService,
)
from gateway.application.ports.oidc import OidcProviderPort
from gateway.domain.auth.errors import OidcIdentityError, OidcStateInvalidError
from gateway.domain.auth.models import (
    AuthAuditEvent,
    AuthenticationDecision,
    IssuedTokens,
    Principal,
    PrincipalType,
    RefreshTokenRecord,
    SessionRecord,
)
from gateway.shared.clock import Clock
from gateway.shared.secrets import generate_token, hash_secret


class CompleteOidcLogin:
    def __init__(
        self,
        *,
        state_store: OidcLoginStateStore,
        provider: OidcProviderPort,
        identities: OAuthIdentityRepository,
        sessions: SessionRepository,
        refresh_tokens: RefreshTokenRepository,
        tokens: TokenService,
        audit: AuthAuditSink,
        clock: Clock,
        access_token_ttl: timedelta = timedelta(minutes=15),
        session_ttl: timedelta = timedelta(days=7),
    ) -> None:
        self._state_store = state_store
        self._provider = provider
        self._identities = identities
        self._sessions = sessions
        self._refresh_tokens = refresh_tokens
        self._tokens = tokens
        self._audit = audit
        self._clock = clock
        self._access_token_ttl = access_token_ttl
        self._session_ttl = session_ttl

    async def execute(
        self,
        *,
        organization_id: UUID,
        state_hash: str,
        code: str,
        redirect_uri: str,
    ) -> IssuedTokens:
        """Finish the login.

        ``organization_id`` and ``state_hash`` must come from an **already HMAC-verified**
        state (the delivery layer verifies before the tenant context is bound).
        """
        now = self._clock.now()

        # (3) Atomic single-use consume. A replayed callback finds nothing and loses here.
        login_state = await self._state_store.consume(state_hash, now=now)
        if login_state is None:
            await self._record(
                AuthenticationDecision.INVALID_TOKEN,
                organization_id,
                detail="oidc_state_unknown_expired_or_replayed",
            )
            raise OidcStateInvalidError("OIDC state is unknown, expired, or already used")

        if login_state.organization_id != organization_id:
            # Defence in depth: RLS should already have made this impossible.
            await self._record(
                AuthenticationDecision.INVALID_TOKEN,
                organization_id,
                detail="oidc_state_tenant_mismatch",
            )
            raise OidcStateInvalidError("OIDC state does not belong to this organization")

        # (4) Redeem the code with the PKCE verifier we stored at /authorize.
        token_response = await self._provider.exchange_code(
            code=code,
            code_verifier=login_state.code_verifier,
            redirect_uri=redirect_uri or login_state.redirect_uri,
        )

        # (5) Verify the id_token. The nonce is matched (by hash) against the one bound to
        #     *this* state row — that is what stops a token minted for another login being
        #     replayed here. Verification raises on any failure; nothing partial is accepted.
        claims = await self._provider.verify_id_token(
            token_response.id_token, expected_nonce_hash=login_state.nonce_hash
        )

        # (6) Map the federated subject to a local user.
        identity = await self._identities.get_by_subject(login_state.provider, claims.subject)
        if identity is None:
            await self._record(
                AuthenticationDecision.INVALID_TOKEN,
                organization_id,
                detail="oidc_identity_unknown",
            )
            raise OidcIdentityError("no local identity is linked to this federated subject")

        # (7) Mint the session and tokens.
        session_id = uuid4()
        await self._sessions.add(
            SessionRecord(
                id=session_id,
                organization_id=organization_id,
                user_id=identity.user_id,
                created_at=now,
                expires_at=now + self._session_ttl,
            )
        )
        principal = Principal(
            principal_type=PrincipalType.USER,
            subject_id=identity.user_id,
            organization_id=organization_id,
        )
        access_token = self._tokens.issue_access_token(
            principal=principal, ttl=self._access_token_ttl
        )
        refresh_token = generate_token()
        await self._refresh_tokens.add(
            RefreshTokenRecord(
                id=uuid4(),
                session_id=session_id,
                organization_id=organization_id,
                token_hash=hash_secret(refresh_token),
                expires_at=now + self._session_ttl,
            )
        )

        await self._record(
            AuthenticationDecision.SUCCESS,
            organization_id,
            subject_id=identity.user_id,
            detail=None,
        )
        return IssuedTokens(access_token=access_token, refresh_token=refresh_token)

    async def _record(
        self,
        decision: AuthenticationDecision,
        organization_id: UUID,
        *,
        subject_id: UUID | None = None,
        detail: str | None = None,
    ) -> None:
        await self._audit.record(
            AuthAuditEvent(
                action="oidc.login",
                result=decision.value,
                organization_id=organization_id,
                principal_type=PrincipalType.USER.value,
                subject_id=subject_id,
                detail=detail,
            )
        )
