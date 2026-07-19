"""OIDC provider adapter — the only place that speaks OIDC over the wire (ADR-0015).

Implements ``OidcProviderPort``: builds the /authorize URL (with PKCE + nonce), redeems the
authorization code, and verifies the ``id_token`` against the cached IdP JWKS. HTTP and the JWT
library live here and nowhere else (import-linter enforces that the application layer cannot
import ``jwt``/``cryptography``).

Every verification failure raises ``IdTokenVerificationError`` — there is no partial-trust path
and no "verify later" mode. Callers fail closed (ADR-0009).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from gateway.adapters.security.jwks_cache import JwksCache, JwksFetchError
from gateway.adapters.security.oidc_state import generate_pkce_pair
from gateway.domain.auth.models import (
    OidcAuthorizationRequest,
    OidcIdTokenClaims,
    OidcTokenResponse,
)
from gateway.observability.logging import get_logger
from gateway.observability.metrics import (
    REASON_MALFORMED,
    REASON_TIMEOUT,
    REASON_TRANSPORT,
    oidc_token_exchange_failures,
)
from gateway.shared.secrets import constant_time_equals, generate_token, sha256_hex

_ALLOWED_ID_TOKEN_ALGORITHMS = ("RS256",)

_logger = get_logger("oidc")


@dataclass(frozen=True, slots=True)
class OidcTimeouts:
    """Network timeout budget for IdP calls (authentication is on the critical path).

    Deterministic failure is preferred over hidden latency: **retries are 0**. A retry would
    multiply worst-case login latency and can silently mask a degraded IdP, so we fail closed
    and surface it via metrics/audit instead. ``total`` is a hard ceiling enforced with
    ``asyncio.timeout`` so connect+read+redirects can never exceed it.
    """

    connect_seconds: float = 2.0
    read_seconds: float = 5.0
    total_seconds: float = 7.0
    retries: int = 0

    def as_httpx(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self.connect_seconds,
            read=self.read_seconds,
            write=self.read_seconds,
            pool=self.connect_seconds,
        )


DEFAULT_OIDC_TIMEOUTS = OidcTimeouts()


class IdTokenVerificationError(Exception):
    """The id_token failed signature, issuer, audience, expiry, or nonce validation."""


class OidcExchangeError(Exception):
    """The authorization-code exchange with the IdP failed."""


@dataclass(frozen=True, slots=True)
class OidcProviderConfig:
    issuer: str
    client_id: str
    client_secret: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    scopes: tuple[str, ...] = ("openid", "profile", "email")


class HttpxJwksTransport:
    """Fetches the JWKS document over HTTPS (satisfies ``JwksTransport``)."""

    def __init__(
        self,
        jwks_uri: str,
        client: httpx.AsyncClient,
        *,
        timeouts: OidcTimeouts = DEFAULT_OIDC_TIMEOUTS,
    ) -> None:
        self._jwks_uri = jwks_uri
        self._client = client
        self._timeouts = timeouts

    async def fetch(self) -> dict[str, Any]:
        """Fetch the JWKS within the total budget. Timeouts surface as ``TimeoutError``."""
        try:
            async with asyncio.timeout(self._timeouts.total_seconds):
                response = await self._client.get(self._jwks_uri, timeout=self._timeouts.as_httpx())
                response.raise_for_status()
                document: dict[str, Any] = response.json()
                return document
        except (TimeoutError, httpx.TimeoutException) as exc:
            # Normalized so JwksCache can label the failure reason as a timeout.
            _logger.warning("oidc_jwks_fetch_timeout", jwks_uri=self._jwks_uri)
            raise TimeoutError("JWKS fetch exceeded the total timeout budget") from exc


class OidcProviderAdapter:
    """Concrete ``OidcProviderPort`` for a standard OIDC authorization-code + PKCE IdP."""

    def __init__(
        self,
        config: OidcProviderConfig,
        jwks_cache: JwksCache,
        client: httpx.AsyncClient,
        *,
        timeouts: OidcTimeouts = DEFAULT_OIDC_TIMEOUTS,
    ) -> None:
        self._config = config
        self._jwks = jwks_cache
        self._client = client
        self._timeouts = timeouts

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> OidcAuthorizationRequest:
        code_verifier, code_challenge = generate_pkce_pair()
        nonce = generate_token()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._config.client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self._config.scopes),
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return OidcAuthorizationRequest(
            authorization_url=f"{self._config.authorization_endpoint}?{query}",
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
        )

    async def exchange_code(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> OidcTokenResponse:
        try:
            async with asyncio.timeout(self._timeouts.total_seconds):
                response = await self._client.post(
                    self._config.token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "client_id": self._config.client_id,
                        "client_secret": self._config.client_secret,
                        "code_verifier": code_verifier,
                    },
                    timeout=self._timeouts.as_httpx(),
                )
                response.raise_for_status()
                payload = response.json()
        except (TimeoutError, httpx.TimeoutException) as exc:
            oidc_token_exchange_failures.labels(reason=REASON_TIMEOUT).inc()
            # Structured and non-sensitive: endpoint only - never code, verifier or secret.
            _logger.warning(
                "oidc_token_exchange_timeout", token_endpoint=self._config.token_endpoint
            )
            raise OidcExchangeError("authorization code exchange timed out") from exc
        except Exception as exc:
            oidc_token_exchange_failures.labels(reason=REASON_TRANSPORT).inc()
            _logger.warning(
                "oidc_token_exchange_failed", token_endpoint=self._config.token_endpoint
            )
            raise OidcExchangeError("authorization code exchange failed") from exc

        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            oidc_token_exchange_failures.labels(reason=REASON_MALFORMED).inc()
            raise OidcExchangeError("token response did not contain an id_token")
        return OidcTokenResponse(
            id_token=id_token,
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
        )

    async def fetch_jwks(self, *, force_refresh: bool = False) -> None:
        if force_refresh:
            await self._jwks.refresh()

    async def verify_id_token(
        self, id_token: str, *, expected_nonce_hash: str
    ) -> OidcIdTokenClaims:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise IdTokenVerificationError("id_token header is unreadable") from exc

        algorithm = header.get("alg")
        if algorithm not in _ALLOWED_ID_TOKEN_ALGORITHMS:
            raise IdTokenVerificationError(f"disallowed id_token algorithm: {algorithm!r}")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise IdTokenVerificationError("id_token has no 'kid'")

        try:
            jwk = await self._jwks.get_key(kid)
        except JwksFetchError as exc:
            raise IdTokenVerificationError(str(exc)) from exc

        try:
            key = RSAAlgorithm.from_jwk(json.dumps(jwk))
            claims = jwt.decode(
                id_token,
                key=key,  # type: ignore[arg-type]
                algorithms=list(_ALLOWED_ID_TOKEN_ALGORITHMS),
                issuer=self._config.issuer,
                audience=self._config.client_id,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise IdTokenVerificationError(f"id_token verification failed: {exc}") from exc

        nonce = claims.get("nonce")
        # Only sha256(nonce) is stored (ADR-0015), so compare hashes — constant time.
        presented_hash = sha256_hex(nonce) if isinstance(nonce, str) else ""
        if not constant_time_equals(presented_hash, expected_nonce_hash):
            raise IdTokenVerificationError("id_token nonce mismatch (possible replay)")

        return OidcIdTokenClaims(
            subject=str(claims["sub"]),
            issuer=str(claims["iss"]),
            audience=self._config.client_id,
            nonce=nonce,
            email=claims.get("email"),
            email_verified=claims.get("email_verified"),
            name=claims.get("name"),
        )
