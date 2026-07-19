"""id_token verification negatives + PKCE/authorize construction (ADR-0015, Security_Test_Plan §1a).

Every row here is an attack the OIDC callback must refuse. Verification is fail-closed: any
signature, issuer, audience, expiry, algorithm, key, or nonce problem raises — there is no
partial-trust path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from gateway.adapters.security.jwks_cache import JwksCache
from gateway.adapters.security.oidc_provider import (
    IdTokenVerificationError,
    OidcProviderAdapter,
    OidcProviderConfig,
)
from gateway.shared.secrets import sha256_b64url, sha256_hex

_ISSUER = "https://idp.example.com"
_CLIENT_ID = "gateway-client"
_NONCE = "nonce-value"
_KID = "key-1"


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)


class StaticTransport:
    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document

    async def fetch(self) -> dict[str, Any]:
        return self._document


def _keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_for(private_key: rsa.RSAPrivateKey, kid: str = _KID) -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = kid
    return {"keys": [jwk]}


def _id_token(
    private_key: rsa.RSAPrivateKey,
    *,
    issuer: str = _ISSUER,
    audience: str = _CLIENT_ID,
    nonce: str | None = _NONCE,
    expires_in: timedelta = timedelta(minutes=5),
    kid: str = _KID,
) -> str:
    # PyJWT checks exp/iat against the *system* clock; a frozen clock made every token
    # look expired, which masked the nonce assertions behind 'Signature has expired'.
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": "user-123",
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
        "email": "user@example.com",
    }
    if nonce is not None:
        claims["nonce"] = nonce
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _adapter(private_key: rsa.RSAPrivateKey, **jwks_kwargs: Any) -> OidcProviderAdapter:
    config = OidcProviderConfig(
        issuer=_ISSUER,
        client_id=_CLIENT_ID,
        client_secret="client-secret",
        authorization_endpoint=f"{_ISSUER}/authorize",
        token_endpoint=f"{_ISSUER}/token",
        jwks_uri=f"{_ISSUER}/jwks",
    )
    document = jwks_kwargs.get("document", _jwks_for(private_key))
    cache = JwksCache(StaticTransport(document), FixedClock())
    return OidcProviderAdapter(config, cache, client=None)  # type: ignore[arg-type]


async def test_valid_id_token_is_accepted() -> None:
    key = _keypair()
    claims = await _adapter(key).verify_id_token(
        _id_token(key), expected_nonce_hash=sha256_hex(_NONCE)
    )

    assert claims.subject == "user-123"
    assert claims.issuer == _ISSUER
    assert claims.nonce == _NONCE


async def test_wrong_issuer_is_rejected() -> None:
    key = _keypair()
    token = _id_token(key, issuer="https://evil.example.com")

    with pytest.raises(IdTokenVerificationError):
        await _adapter(key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_wrong_audience_is_rejected() -> None:
    key = _keypair()
    token = _id_token(key, audience="some-other-client")

    with pytest.raises(IdTokenVerificationError):
        await _adapter(key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_expired_id_token_is_rejected() -> None:
    key = _keypair()
    token = _id_token(key, expires_in=timedelta(minutes=-5))

    with pytest.raises(IdTokenVerificationError):
        await _adapter(key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_token_signed_by_unknown_key_is_rejected() -> None:
    """Signed by an attacker's key that is absent from the IdP JWKS."""
    attacker_key, real_key = _keypair(), _keypair()
    token = _id_token(attacker_key)

    # JWKS advertises the *real* key under the same kid, so the signature cannot verify.
    with pytest.raises(IdTokenVerificationError):
        await _adapter(real_key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_unknown_kid_fails_closed() -> None:
    key = _keypair()
    token = _id_token(key, kid="rotated-away-kid")

    with pytest.raises(IdTokenVerificationError):
        await _adapter(key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_nonce_mismatch_is_rejected_as_replay() -> None:
    key = _keypair()
    token = _id_token(key, nonce="a-different-nonce")

    with pytest.raises(IdTokenVerificationError, match="nonce"):
        await _adapter(key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_missing_nonce_is_rejected() -> None:
    key = _keypair()
    token = _id_token(key, nonce=None)

    with pytest.raises(IdTokenVerificationError, match="nonce"):
        await _adapter(key).verify_id_token(token, expected_nonce_hash=sha256_hex(_NONCE))


async def test_alg_none_is_rejected() -> None:
    """Algorithm confusion: an unsigned token must never be accepted."""
    key = _keypair()
    now = datetime.now(UTC)
    forged = jwt.encode(
        {
            "sub": "u",
            "iss": _ISSUER,
            "aud": _CLIENT_ID,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        key="",
        algorithm="none",
        headers={"kid": _KID},
    )

    with pytest.raises(IdTokenVerificationError, match="algorithm"):
        await _adapter(key).verify_id_token(forged, expected_nonce_hash=sha256_hex(_NONCE))


async def test_tampered_payload_is_rejected() -> None:
    key = _keypair()
    header, payload, signature = _id_token(key).split(".")
    tampered = f"{header}.{payload[:-2]}XY.{signature}"

    with pytest.raises(IdTokenVerificationError):
        await _adapter(key).verify_id_token(tampered, expected_nonce_hash=sha256_hex(_NONCE))


async def test_unreadable_token_is_rejected() -> None:
    key = _keypair()

    with pytest.raises(IdTokenVerificationError):
        await _adapter(key).verify_id_token("not-a-jwt", expected_nonce_hash=sha256_hex(_NONCE))


def test_authorization_url_carries_pkce_s256_state_and_nonce() -> None:
    key = _keypair()
    request = _adapter(key).build_authorization_url(
        state="signed-state", redirect_uri="https://gw.example/callback"
    )
    params = parse_qs(urlparse(request.authorization_url).query)

    assert params["response_type"] == ["code"]
    assert params["state"] == ["signed-state"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == [sha256_b64url(request.code_verifier)]
    assert params["nonce"] == [request.nonce]
    assert request.code_verifier not in request.authorization_url, (
        "the PKCE verifier must never be sent to the IdP in the authorize request"
    )


def test_timeout_policy_is_deterministic_and_retry_free() -> None:
    """Authentication is on the critical path: bounded, no hidden retries (ADR-0015)."""
    from gateway.adapters.security.oidc_provider import DEFAULT_OIDC_TIMEOUTS

    assert DEFAULT_OIDC_TIMEOUTS.connect_seconds == 2.0
    assert DEFAULT_OIDC_TIMEOUTS.read_seconds == 5.0
    assert DEFAULT_OIDC_TIMEOUTS.total_seconds == 7.0
    assert DEFAULT_OIDC_TIMEOUTS.retries == 0, "retries must be 0 — fail closed, don't mask latency"
    assert DEFAULT_OIDC_TIMEOUTS.total_seconds >= (
        DEFAULT_OIDC_TIMEOUTS.connect_seconds + DEFAULT_OIDC_TIMEOUTS.read_seconds
    ), "total budget must cover connect + read"
