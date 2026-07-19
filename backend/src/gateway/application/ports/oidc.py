"""OIDC provider port (ADR-0015).

The application layer drives federated login through this port only — it never performs HTTP,
never parses JWKS, and never touches a crypto library (import-linter enforced). The adapter
(``adapters/security/oidc_provider.py``) owns the network and cryptography; tests substitute a
fake. This also lets multiple/per-tenant IdPs land later without changing the use-cases.
"""

from __future__ import annotations

from typing import Protocol

from gateway.domain.auth.models import (
    OidcAuthorizationRequest,
    OidcIdTokenClaims,
    OidcTokenResponse,
)


class OidcProviderPort(Protocol):
    """Everything the OIDC authorization-code + PKCE flow needs from an identity provider."""

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> OidcAuthorizationRequest:
        """Create the /authorize URL plus the state/nonce/PKCE material to persist."""
        ...

    async def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> OidcTokenResponse:
        """Redeem a single-use authorization code (with the PKCE verifier) for tokens."""
        ...

    async def fetch_jwks(self, *, force_refresh: bool = False) -> None:
        """Populate/refresh the cached signing keys. Fails closed if unreachable/malformed."""
        ...

    async def verify_id_token(
        self, id_token: str, *, expected_nonce_hash: str
    ) -> OidcIdTokenClaims:
        """Verify signature, ``iss``, ``aud``, ``exp`` and ``nonce``. Raises on any failure.

        The nonce is matched by **hash**: only ``sha256(nonce)`` is persisted in
        ``oidc_login_state``, so the adapter hashes the presented claim and compares in
        constant time. Passing a raw nonce here would never match a stored hash.
        """
        ...
