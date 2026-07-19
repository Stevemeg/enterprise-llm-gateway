"""In-memory fakes for auth ports (behavioral doubles for unit tests)."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from gateway.domain.auth.models import (
    ApiKeyRecord,
    AuthAuditEvent,
    OAuthIdentityRecord,
    OidcAuthorizationRequest,
    OidcIdTokenClaims,
    OidcLoginStateRecord,
    OidcTokenResponse,
    Principal,
    RefreshTokenRecord,
    ServiceAccountCredentialRecord,
    ServiceAccountRecord,
    SessionRecord,
)
from gateway.shared.secrets import sha256_hex


class InMemoryApiKeyRepository:
    def __init__(self) -> None:
        self._by_prefix: dict[str, ApiKeyRecord] = {}

    def store(self, prefix: str, record: ApiKeyRecord) -> None:
        self._by_prefix[prefix] = record

    async def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        return self._by_prefix.get(prefix)


class InMemoryServiceAccountRepository:
    def __init__(self) -> None:
        self._by_client_id: dict[str, ServiceAccountRecord] = {}

    def store(self, client_id: str, record: ServiceAccountRecord) -> None:
        self._by_client_id[client_id] = record

    async def get_by_client_id(self, client_id: str) -> ServiceAccountRecord | None:
        return self._by_client_id.get(client_id)


class InMemorySessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[UUID, SessionRecord] = {}

    async def add(self, record: SessionRecord) -> None:
        self.sessions[record.id] = record

    async def get(self, session_id: UUID) -> SessionRecord | None:
        return self.sessions.get(session_id)

    async def revoke(self, session_id: UUID) -> None:
        current = self.sessions.get(session_id)
        if current is not None:
            self.sessions[session_id] = SessionRecord(
                id=current.id,
                user_id=current.user_id,
                organization_id=current.organization_id,
                created_at=current.created_at,
                expires_at=current.expires_at,
                revoked_at=current.created_at,
            )


class InMemoryRefreshTokenRepository:
    def __init__(self) -> None:
        self.by_hash: dict[str, RefreshTokenRecord] = {}
        self.revoked_sessions: set[UUID] = set()

    async def add(self, record: RefreshTokenRecord) -> None:
        self.by_hash[record.token_hash] = record

    async def get_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        return self.by_hash.get(token_hash)

    async def mark_rotated(self, token_id: UUID, rotated_to: UUID) -> None:
        for key, record in list(self.by_hash.items()):
            if record.id == token_id:
                self.by_hash[key] = RefreshTokenRecord(
                    id=record.id,
                    session_id=record.session_id,
                    organization_id=record.organization_id,
                    token_hash=record.token_hash,
                    expires_at=record.expires_at,
                    rotated_to=rotated_to,
                    revoked_at=record.revoked_at,
                )

    async def revoke_session_tokens(self, session_id: UUID) -> None:
        self.revoked_sessions.add(session_id)
        for key, record in list(self.by_hash.items()):
            if record.session_id == session_id:
                self.by_hash[key] = RefreshTokenRecord(
                    id=record.id,
                    session_id=record.session_id,
                    organization_id=record.organization_id,
                    token_hash=record.token_hash,
                    expires_at=record.expires_at,
                    rotated_to=record.rotated_to,
                    revoked_at=record.expires_at,
                )


class FakeTokenService:
    """Deterministic token 'issuer' for use-case tests (no real crypto)."""

    def __init__(self) -> None:
        self.issued: list[Principal] = []

    def issue_access_token(self, *, principal: Principal, ttl: timedelta) -> str:
        self.issued.append(principal)
        return f"access.{principal.principal_type.value}.{principal.subject_id}"


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[AuthAuditEvent] = []

    async def record(self, event: AuthAuditEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[str]:
        return [event.action for event in self.events]


class InMemoryServiceAccountCredentialRepository:
    def __init__(self) -> None:
        self._by_client_id: dict[str, ServiceAccountCredentialRecord] = {}

    def store(self, record: ServiceAccountCredentialRecord) -> None:
        self._by_client_id[record.client_id] = record

    async def add(self, record: ServiceAccountCredentialRecord) -> None:
        self._by_client_id[record.client_id] = record

    async def get_by_client_id(self, client_id: str) -> ServiceAccountCredentialRecord | None:
        return self._by_client_id.get(client_id)

    async def revoke(self, credential_id: UUID) -> None:
        for key, record in list(self._by_client_id.items()):
            if record.id == credential_id:
                self._by_client_id[key] = ServiceAccountCredentialRecord(
                    id=record.id,
                    service_account_id=record.service_account_id,
                    organization_id=record.organization_id,
                    client_id=record.client_id,
                    secret_hash=record.secret_hash,
                    status="revoked",
                    expires_at=record.expires_at,
                )


class InMemoryOAuthIdentityRepository:
    def __init__(self) -> None:
        self._by_subject: dict[tuple[str, str], OAuthIdentityRecord] = {}

    async def add(self, record: OAuthIdentityRecord) -> None:
        self._by_subject[(record.provider, record.subject)] = record

    async def get_by_subject(self, provider: str, subject: str) -> OAuthIdentityRecord | None:
        return self._by_subject.get((provider, subject))


class InMemoryOidcLoginStateStore:
    """Single-use OIDC state store (mirrors the Postgres DELETE..RETURNING semantics).

    ``consume`` pops — a second call for the same state finds nothing, exactly like the real
    adapter losing the race. Expired records are treated as absent (fail closed).
    """

    def __init__(self) -> None:
        self._records: dict[str, OidcLoginStateRecord] = {}

    async def save(self, record: OidcLoginStateRecord) -> None:
        self._records[record.state_hash] = record

    async def consume(self, state_hash: str, *, now: datetime) -> OidcLoginStateRecord | None:
        record = self._records.pop(state_hash, None)  # single-use: gone either way
        if record is None or record.expires_at <= now:
            return None
        return record

    async def purge_expired(self, *, now: datetime) -> int:
        stale = [h for h, r in self._records.items() if r.expires_at <= now]
        for h in stale:
            del self._records[h]
        return len(stale)


class FakeOidcProvider:
    """Scripted OIDC provider (no HTTP, no crypto) implementing ``OidcProviderPort``."""

    def __init__(
        self,
        *,
        subject: str = "idp-subject-1",
        nonce: str = "the-nonce",
        expected_nonce_hash_override: str | None = None,
    ) -> None:
        self._subject = subject
        self._nonce = nonce
        self._override = expected_nonce_hash_override
        self.exchanges: list[str] = []

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> OidcAuthorizationRequest:
        return OidcAuthorizationRequest(
            authorization_url=f"https://idp.example/authorize?state={state}",
            state=state,
            nonce=self._nonce,
            code_verifier="verifier",
            code_challenge="challenge",
        )

    async def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> OidcTokenResponse:
        self.exchanges.append(code)
        return OidcTokenResponse(id_token="fake.id.token", access_token="idp-access")

    async def fetch_jwks(self, *, force_refresh: bool = False) -> None:
        return None

    async def verify_id_token(
        self, id_token: str, *, expected_nonce_hash: str
    ) -> OidcIdTokenClaims:
        # The real adapter hashes the presented nonce and compares; mirror that contract.
        presented = self._override if self._override is not None else sha256_hex(self._nonce)
        if presented != expected_nonce_hash:
            raise AssertionError("id_token nonce mismatch (possible replay)")
        return OidcIdTokenClaims(
            subject=self._subject,
            issuer="https://idp.example",
            audience="gateway-client",
            nonce=self._nonce,
            email="user@example.com",
        )
