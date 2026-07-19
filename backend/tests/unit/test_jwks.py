"""Tests for JWKS document construction."""

from __future__ import annotations

from gateway.adapters.security.jwks import build_jwks
from gateway.adapters.security.keys import generate_signing_key


def test_build_jwks_exposes_public_key_material() -> None:
    keys = [generate_signing_key("kid-a").to_verification_key()]
    jwks = build_jwks(keys)
    assert len(jwks["keys"]) == 1
    jwk = jwks["keys"][0]
    assert jwk["kty"] == "RSA"
    assert jwk["use"] == "sig"
    assert jwk["alg"] == "RS256"
    assert jwk["kid"] == "kid-a"
    assert jwk["n"]  # base64url modulus
    assert jwk["e"]  # base64url exponent


def test_build_jwks_supports_rotation_set() -> None:
    keys = [
        generate_signing_key("current").to_verification_key(),
        generate_signing_key("previous").to_verification_key(),
    ]
    jwks = build_jwks(keys)
    assert {k["kid"] for k in jwks["keys"]} == {"current", "previous"}
