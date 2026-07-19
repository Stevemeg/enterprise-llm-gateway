"""JWT-backed access-token service (implements TokenService + AccessTokenVerifier).

Bridges the application ports to the crypto adapters: issues signed access tokens with
the current key and validates them against the current + previous keys (rotation-safe).
The principal type rides in a ``ptyp`` claim so verification reconstructs the principal.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.domain.auth.errors import TokenInvalidError
from gateway.domain.auth.models import Principal, PrincipalType

_PRINCIPAL_TYPE_CLAIM = "ptyp"


class JwtTokenService:
    def __init__(self, jwt_service: JwtService, key_provider: KeyProvider) -> None:
        self._jwt = jwt_service
        self._keys = key_provider

    def issue_access_token(self, *, principal: Principal, ttl: timedelta) -> str:
        return self._jwt.issue(
            signing_key=self._keys.current_signing_key(),
            subject=str(principal.subject_id),
            organization_id=str(principal.organization_id),
            token_type="access",
            scopes=principal.scopes,
            ttl=ttl,
            additional_claims={_PRINCIPAL_TYPE_CLAIM: principal.principal_type.value},
        )

    def verify(self, token: str) -> Principal:
        claims = self._jwt.verify(token, verification_keys=self._keys.verification_keys())
        raw_type = claims.additional.get(_PRINCIPAL_TYPE_CLAIM, PrincipalType.USER.value)
        try:
            principal_type = PrincipalType(raw_type)
            subject_id = UUID(claims.subject)
            organization_id = UUID(claims.organization_id)
        except ValueError as exc:
            raise TokenInvalidError("malformed principal claims") from exc
        return Principal(
            principal_type=principal_type,
            subject_id=subject_id,
            organization_id=organization_id,
            scopes=claims.scopes,
        )
