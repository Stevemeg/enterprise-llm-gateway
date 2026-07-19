"""Tests for the signing-key provider (rotation + JWKS)."""

from __future__ import annotations

from gateway.adapters.security.key_provider import KeyProvider


def test_generate_exposes_current_key() -> None:
    provider = KeyProvider.generate("gateway-1")
    assert provider.current_signing_key().kid == "gateway-1"
    assert set(provider.verification_keys()) == {"gateway-1"}


def test_jwks_contains_current_key() -> None:
    provider = KeyProvider.generate("gateway-1")
    kids = {k["kid"] for k in provider.jwks()["keys"]}
    assert kids == {"gateway-1"}


def test_rotation_retains_previous_public_key() -> None:
    provider = KeyProvider.generate("gateway-1").rotate("gateway-2")
    assert provider.current_signing_key().kid == "gateway-2"
    # both keys verify (grace window); JWKS exposes both
    assert set(provider.verification_keys()) == {"gateway-1", "gateway-2"}
    assert {k["kid"] for k in provider.jwks()["keys"]} == {"gateway-1", "gateway-2"}
