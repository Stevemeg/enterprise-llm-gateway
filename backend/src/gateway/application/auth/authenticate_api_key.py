"""Authenticate an application via a virtual API key (Authentication_Architecture.md §7).

Looks up by non-secret prefix, then verifies the presented secret against the stored
SHA-256 hash in **constant time**. Any failure raises ``CredentialInvalidError`` (401).
"""

from __future__ import annotations

from gateway.application.ports.auth import ApiKeyRepository
from gateway.domain.auth.errors import CredentialInvalidError
from gateway.domain.auth.models import Principal, PrincipalType
from gateway.shared.auth_constants import API_KEY_PREFIX_LENGTH
from gateway.shared.clock import Clock
from gateway.shared.secrets import verify_secret


class AuthenticateApiKey:
    def __init__(self, api_keys: ApiKeyRepository, clock: Clock) -> None:
        self._api_keys = api_keys
        self._clock = clock

    async def __call__(self, presented_secret: str) -> Principal:
        record = await self._api_keys.get_by_prefix(presented_secret[:API_KEY_PREFIX_LENGTH])
        if record is None or not record.is_active:
            raise CredentialInvalidError("invalid API key")
        if record.expires_at is not None and self._clock.now() > record.expires_at:
            raise CredentialInvalidError("API key expired")
        if not verify_secret(presented_secret, record.key_hash):
            raise CredentialInvalidError("invalid API key")
        return Principal(
            principal_type=PrincipalType.API_KEY,
            subject_id=record.id,
            organization_id=record.organization_id,
            scopes=record.scopes,
        )
