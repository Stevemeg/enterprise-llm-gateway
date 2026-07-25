"""Resolve a bearer credential to a principal (Authentication_Architecture.md §2).

Routes API keys (``elg_`` prefix) to the key-verification use-case and everything else to
the JWT verifier. Fails closed: any failure propagates as an ``AuthError`` (401 at edge).
"""

from __future__ import annotations

from gateway.application.auth.authenticate_api_key import AuthenticateApiKey
from gateway.application.ports.auth import AccessTokenVerifier
from gateway.domain.auth.models import Principal
from gateway.shared.auth_constants import API_KEY_PREFIX


class CompositeAuthenticator:
    def __init__(
        self, api_key_authenticator: AuthenticateApiKey, token_verifier: AccessTokenVerifier
    ) -> None:
        self._api_key = api_key_authenticator
        self._tokens = token_verifier

    async def authenticate(self, credential: str) -> Principal:
        if credential.startswith(API_KEY_PREFIX):
            return await self._api_key(credential)
        return self._tokens.verify(credential)
