"""Tests for JWT issuance and validation (correctness + failure modes + security)."""

from __future__ import annotations

from datetime import timedelta

import jwt as pyjwt
import pytest

from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.keys import SigningKey, generate_signing_key
from gateway.domain.auth.errors import TokenExpiredError, TokenInvalidError
from tests.conftest import FixedClock

_ISSUER = "https://gateway.example.com"
_AUDIENCE = "gateway"


def _service(leeway: int = 60) -> JwtService:
    return JwtService(issuer=_ISSUER, audience=_AUDIENCE, clock=FixedClock(), leeway_seconds=leeway)


def _issue(service: JwtService, key: SigningKey, ttl: timedelta = timedelta(minutes=10)) -> str:
    return service.issue(
        signing_key=key,
        subject="user-1",
        organization_id="org-1",
        token_type="access",
        scopes=["infer:chat"],
        ttl=ttl,
    )


def test_issue_and_verify_roundtrip() -> None:
    service = _service()
    key = generate_signing_key("kid-1")
    token = _issue(service, key)
    claims = service.verify(token, verification_keys={"kid-1": key.public_pem})
    assert claims.subject == "user-1"
    assert claims.organization_id == "org-1"
    assert claims.token_type == "access"
    assert claims.scopes == ("infer:chat",)
    assert claims.jti


def test_expired_token_is_rejected() -> None:
    service = _service(leeway=0)
    key = generate_signing_key("kid-1")
    token = _issue(service, key, ttl=timedelta(seconds=-30))
    with pytest.raises(TokenExpiredError):
        service.verify(token, verification_keys={"kid-1": key.public_pem})


def test_within_clock_skew_is_accepted() -> None:
    service = _service(leeway=60)
    key = generate_signing_key("kid-1")
    token = _issue(service, key, ttl=timedelta(seconds=-30))  # expired 30s, within 60s leeway
    claims = service.verify(token, verification_keys={"kid-1": key.public_pem})
    assert claims.subject == "user-1"


def test_tampered_signature_is_rejected() -> None:
    service = _service()
    key = generate_signing_key("kid-1")
    token = _issue(service, key)
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    with pytest.raises(TokenInvalidError):
        service.verify(tampered, verification_keys={"kid-1": key.public_pem})


def test_unknown_kid_is_rejected() -> None:
    service = _service()
    key = generate_signing_key("kid-1")
    token = _issue(service, key)
    with pytest.raises(TokenInvalidError, match="kid"):
        service.verify(token, verification_keys={"other-kid": key.public_pem})


def test_wrong_key_is_rejected() -> None:
    service = _service()
    signer = generate_signing_key("kid-1")
    attacker = generate_signing_key("kid-1")
    token = _issue(service, signer)
    with pytest.raises(TokenInvalidError):
        service.verify(token, verification_keys={"kid-1": attacker.public_pem})


def test_algorithm_confusion_is_rejected() -> None:
    # A token advertising a symmetric algorithm must be rejected by our allow-list,
    # regardless of the secret used to forge it.
    service = _service()
    key = generate_signing_key("kid-1")
    forged = pyjwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "attacker",
            "jti": "x",
            "iat": 0,
            "nbf": 0,
            "exp": 9999999999,
        },
        "attacker-chosen-secret",
        algorithm="HS256",
        headers={"kid": "kid-1"},
    )
    with pytest.raises(TokenInvalidError, match="algorithm not allowed"):
        service.verify(forged, verification_keys={"kid-1": key.public_pem})


def test_wrong_audience_is_rejected() -> None:
    service = _service()
    key = generate_signing_key("kid-1")
    token = _issue(service, key)
    other = JwtService(issuer=_ISSUER, audience="someone-else", clock=FixedClock())
    with pytest.raises(TokenInvalidError):
        other.verify(token, verification_keys={"kid-1": key.public_pem})
