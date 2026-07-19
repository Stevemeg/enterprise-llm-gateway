"""JWT issuance & validation (Authentication_Architecture.md §4, ADR-0008).

RS256 with ``kid``-based key selection, an explicit algorithm allow-list (rejects
``alg:none`` and HMAC alg-confusion), injected-clock expiry/nbf checks with skew leeway,
and issuer/audience validation. Raises framework-free auth errors; the edge maps them to 401.
Non-standard claims may be attached via ``additional_claims`` and are returned in
``TokenClaims.additional`` (e.g., the principal type).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import jwt as pyjwt

from gateway.adapters.security.keys import SigningKey
from gateway.domain.auth.errors import TokenExpiredError, TokenInvalidError
from gateway.shared.clock import Clock
from gateway.shared.secrets import generate_hex

_ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256",)
_RESERVED_CLAIMS = frozenset(
    {"iss", "aud", "sub", "org", "typ", "scope", "jti", "iat", "nbf", "exp"}
)


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Validated claims from a gateway JWT."""

    subject: str
    organization_id: str
    token_type: str
    scopes: tuple[str, ...]
    jti: str
    issued_at: datetime
    expires_at: datetime
    additional: Mapping[str, str] = field(default_factory=dict)


class JwtService:
    """Issues and validates RS256 JWTs against an injected clock."""

    def __init__(
        self, *, issuer: str, audience: str, clock: Clock, leeway_seconds: int = 60
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._clock = clock
        self._leeway = timedelta(seconds=leeway_seconds)

    def issue(
        self,
        *,
        signing_key: SigningKey,
        subject: str,
        organization_id: str,
        token_type: str,
        scopes: Sequence[str],
        ttl: timedelta,
        additional_claims: Mapping[str, str] | None = None,
    ) -> str:
        """Sign a new JWT. ``ttl`` may be negative in tests to produce an expired token."""
        now = self._clock.now()
        payload: dict[str, object] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": subject,
            "org": organization_id,
            "typ": token_type,
            "scope": " ".join(scopes),
            "jti": generate_hex(16),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
        }
        for key, value in (additional_claims or {}).items():
            if key in _RESERVED_CLAIMS:
                raise ValueError(f"additional claim {key!r} collides with a reserved claim")
            payload[key] = value
        return pyjwt.encode(
            payload,
            signing_key.private_pem,
            algorithm="RS256",
            headers={"kid": signing_key.kid},
        )

    def verify(self, token: str, *, verification_keys: Mapping[str, str]) -> TokenClaims:
        """Validate signature, algorithm, kid, issuer/audience, and expiry (with leeway).

        Time validation uses the injected clock (deterministic + testable); PyJWT verifies
        the signature and iss/aud.
        """
        try:
            header = pyjwt.get_unverified_header(token)
        except pyjwt.InvalidTokenError as exc:
            raise TokenInvalidError("malformed token header") from exc

        algorithm = header.get("alg")
        if algorithm not in _ALLOWED_ALGORITHMS:
            raise TokenInvalidError(f"algorithm not allowed: {algorithm!r}")
        kid = header.get("kid")
        if not isinstance(kid, str) or kid not in verification_keys:
            raise TokenInvalidError("unknown or missing kid")

        try:
            claims = pyjwt.decode(
                token,
                verification_keys[kid],
                algorithms=list(_ALLOWED_ALGORITHMS),
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "verify_exp": False,
                    "verify_nbf": False,
                    "require": ["exp", "iat", "nbf", "sub", "jti"],
                },
            )
        except pyjwt.InvalidTokenError as exc:
            raise TokenInvalidError(str(exc)) from exc

        now = self._clock.now()
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        not_before = datetime.fromtimestamp(int(claims["nbf"]), tz=UTC)
        if now > expires_at + self._leeway:
            raise TokenExpiredError("token expired")
        if now < not_before - self._leeway:
            raise TokenInvalidError("token not yet valid")

        scope_value = claims.get("scope", "")
        scopes = tuple(scope_value.split()) if scope_value else ()
        additional = {k: str(v) for k, v in claims.items() if k not in _RESERVED_CLAIMS}
        return TokenClaims(
            subject=str(claims["sub"]),
            organization_id=str(claims.get("org", "")),
            token_type=str(claims.get("typ", "")),
            scopes=scopes,
            jti=str(claims["jti"]),
            issued_at=datetime.fromtimestamp(int(claims["iat"]), tz=UTC),
            expires_at=expires_at,
            additional=additional,
        )
