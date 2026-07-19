"""Authentication domain errors (ADR-0008, Authentication_Architecture.md §18).

All fail closed at the edge (mapped to HTTP 401). Kept framework-free.
"""

from __future__ import annotations

from gateway.domain.errors import DomainError


class AuthError(DomainError):
    """Base class for authentication failures."""


class TokenInvalidError(AuthError):
    """Token signature/claims/algorithm/kid failed validation."""


class TokenExpiredError(AuthError):
    """Token is past its expiry (beyond clock-skew leeway)."""


class RefreshReuseError(AuthError):
    """A rotated/revoked refresh token was presented — theft signal; session revoked."""


class CredentialInvalidError(AuthError):
    """A presented secret (API key / service-account secret) did not verify."""


class SessionRevokedError(AuthError):
    """The session backing a token has been revoked or expired."""


class OidcStateInvalidError(AuthError):
    """The OIDC ``state`` was forged, malformed, expired, unknown, or already consumed (replay)."""


class OidcIdentityError(AuthError):
    """The verified id_token does not map to a usable local identity."""
