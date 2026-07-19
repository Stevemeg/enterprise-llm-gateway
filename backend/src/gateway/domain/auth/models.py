"""Authentication domain value objects (framework-free).

Principals, credential records (read models used by repositories), and issued tokens.
These are plain immutable dataclasses — no ORM, no framework types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ApiKeyStatus(StrEnum):
    """Lifecycle status of an API key / service-account credential.

    Mirrors the PostgreSQL ``api_key_status`` ENUM exactly. Passing a bare string where the
    database expects this enum makes asyncpg reject the statement, so the Core table
    definitions bind to this type and repositories pass members rather than literals.
    """

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class PrincipalType(StrEnum):
    USER = "user"
    SERVICE_ACCOUNT = "service_account"
    API_KEY = "api_key"


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated identity attached to a request."""

    principal_type: PrincipalType
    subject_id: UUID
    organization_id: UUID
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: UUID
    organization_id: UUID
    key_hash: str
    scopes: tuple[str, ...]
    is_active: bool
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ServiceAccountRecord:
    id: UUID
    organization_id: UUID
    secret_hash: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: UUID
    user_id: UUID
    organization_id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RefreshTokenRecord:
    id: UUID
    session_id: UUID
    organization_id: UUID
    token_hash: str
    expires_at: datetime
    rotated_to: UUID | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class ServiceAccountCredentialRecord:
    id: UUID
    service_account_id: UUID
    organization_id: UUID
    client_id: str
    secret_hash: str
    status: str
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OAuthIdentityRecord:
    id: UUID
    organization_id: UUID
    user_id: UUID
    provider: str
    subject: str


@dataclass(frozen=True, slots=True)
class AuthAuditEvent:
    action: str
    result: str
    organization_id: UUID | None = None
    principal_type: str | None = None
    subject_id: UUID | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class OidcLoginStateRecord:
    """Single-use OIDC login state held between /authorize and /callback (ADR-0015).

    ``state_hash``/``nonce_hash`` are hex-encoded SHA-256 digests — the raw ``state`` and
    ``nonce`` are never stored. ``code_verifier`` is the transient PKCE secret, deleted on
    consume. A record whose ``expires_at`` has passed is treated as absent (fail closed).
    """

    id: UUID
    organization_id: UUID
    state_hash: str
    nonce_hash: str
    code_verifier: str
    provider: str
    redirect_uri: str
    expires_at: datetime
    code_challenge_method: str = "S256"
    return_to: str | None = None


@dataclass(frozen=True, slots=True)
class OidcAuthorizationRequest:
    """What /authorize produced: where to send the user, plus the secrets to remember."""

    authorization_url: str
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    code_challenge_method: str = "S256"


@dataclass(frozen=True, slots=True)
class OidcTokenResponse:
    """Raw token-endpoint result; ``id_token`` is verified before any of it is trusted."""

    id_token: str
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


@dataclass(frozen=True, slots=True)
class OidcIdTokenClaims:
    """Verified id_token claims (signature, iss, aud, exp and nonce already checked)."""

    subject: str
    issuer: str
    audience: str
    nonce: str | None = None
    email: str | None = None
    email_verified: bool | None = None
    name: str | None = None


class AuthenticationMethod(StrEnum):
    """How a request proved its identity. Used as a *metric label* — keep it low-cardinality."""

    JWT = "jwt"
    API_KEY = "api_key"
    SERVICE_ACCOUNT = "service_account"
    OIDC = "oidc"


class AuthenticationDecision(StrEnum):
    """The single vocabulary for every authentication outcome.

    Centralising these prevents ad-hoc strings ("failed", "bad token", "expired") drifting
    across middleware, use-cases, and audit records. Every ``AuthAuditEvent`` and every
    authentication metric uses a member of this enum — so audit queries and dashboards stay
    stable, and a new outcome must be added here deliberately rather than invented inline.
    """

    SUCCESS = "success"
    INVALID_TOKEN = "invalid_token"
    INVALID_KEY = "invalid_key"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INSUFFICIENT_SCOPE = "insufficient_scope"
    UNKNOWN_KID = "unknown_kid"
    CLOCK_SKEW = "clock_skew"
    INTERNAL_ERROR = "internal_error"

    @property
    def is_success(self) -> bool:
        return self is AuthenticationDecision.SUCCESS


@dataclass(frozen=True, slots=True)
class AuthenticationContext:
    """The **one** immutable object the middleware attaches to an authenticated request.

    Downstream code (authorization, handlers, audit) reads this instead of poking arbitrary
    attributes onto ``request.state``. That keeps the contract explicit and typed, stops
    attribute sprawl, and gives RBAC a single well-defined input. Reserved slots
    (``mfa_satisfied``, ``device_id``) exist so step-up auth and device binding can be added
    later without changing every consumer.
    """

    principal_id: UUID
    principal_type: PrincipalType
    organization_id: UUID
    authentication_method: AuthenticationMethod
    scopes: tuple[str, ...] = ()
    session_id: UUID | None = None
    mfa_satisfied: bool = False
    device_id: str | None = None

    @classmethod
    def from_principal(
        cls,
        principal: Principal,
        *,
        authentication_method: AuthenticationMethod,
        session_id: UUID | None = None,
    ) -> AuthenticationContext:
        return cls(
            principal_id=principal.subject_id,
            principal_type=principal.principal_type,
            organization_id=principal.organization_id,
            authentication_method=authentication_method,
            scopes=principal.scopes,
            session_id=session_id,
        )

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes
