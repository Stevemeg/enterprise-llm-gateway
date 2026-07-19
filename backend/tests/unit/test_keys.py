"""Tests for RSA signing-key generation."""

from __future__ import annotations

from gateway.adapters.security.keys import generate_signing_key


def test_generate_signing_key_produces_pem_pair() -> None:
    key = generate_signing_key("kid-1")
    assert key.kid == "kid-1"
    assert "BEGIN PRIVATE KEY" in key.private_pem
    assert "BEGIN PUBLIC KEY" in key.public_pem


def test_to_verification_key_is_public_only() -> None:
    key = generate_signing_key("kid-2")
    verification = key.to_verification_key()
    assert verification.kid == "kid-2"
    assert verification.public_pem == key.public_pem
