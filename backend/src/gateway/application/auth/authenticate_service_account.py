"""Authenticate a service account via client credentials (Authentication_Architecture.md §8).

Looks up the credential by ``client_id``, verifies the secret in constant time, checks
status/expiry, and issues a short access token (no refresh). Realizes ADR-0013 (credentials
in a dedicated table).
"""

from __future__ import annotations

from datetime import timedelta

from gateway.application.ports.auth import ServiceAccountCredentialRepository, TokenService
from gateway.domain.auth.errors import CredentialInvalidError
from gateway.domain.auth.models import Principal, PrincipalType
from gateway.shared.clock import Clock
from gateway.shared.secrets import verify_secret

_ACTIVE = "active"


class AuthenticateServiceAccount:
    def __init__(
        self,
        credentials: ServiceAccountCredentialRepository,
        token_service: TokenService,
        clock: Clock,
        *,
        access_ttl: timedelta,
    ) -> None:
        self._credentials = credentials
        self._token_service = token_service
        self._clock = clock
        self._access_ttl = access_ttl

    async def __call__(self, client_id: str, client_secret: str) -> str:
        record = await self._credentials.get_by_client_id(client_id)
        if record is None or record.status != _ACTIVE:
            raise CredentialInvalidError("invalid client credentials")
        if record.expires_at is not None and self._clock.now() > record.expires_at:
            raise CredentialInvalidError("client credential expired")
        if not verify_secret(client_secret, record.secret_hash):
            raise CredentialInvalidError("invalid client credentials")
        principal = Principal(
            principal_type=PrincipalType.SERVICE_ACCOUNT,
            subject_id=record.service_account_id,
            organization_id=record.organization_id,
        )
        return self._token_service.issue_access_token(principal=principal, ttl=self._access_ttl)
