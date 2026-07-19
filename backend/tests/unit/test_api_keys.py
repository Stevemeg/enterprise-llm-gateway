"""Tests for API key generation and timing-safe verification."""

from __future__ import annotations

from gateway.adapters.security.api_keys import (
    extract_prefix,
    generate_api_key,
    verify_api_key,
)


def test_generated_key_shape_and_storage() -> None:
    key = generate_api_key("live")
    assert key.secret.startswith("elg_live_")
    assert key.prefix == key.secret[:16]
    assert key.secret not in key.key_hash  # only a hash is stored
    assert len(key.key_hash) == 64  # sha256 hex


def test_verification_accepts_correct_and_rejects_wrong() -> None:
    key = generate_api_key()
    assert verify_api_key(key.secret, key.key_hash) is True
    assert verify_api_key(key.secret + "x", key.key_hash) is False


def test_two_keys_are_distinct() -> None:
    a = generate_api_key()
    b = generate_api_key()
    assert a.secret != b.secret
    assert a.key_hash != b.key_hash


def test_extract_prefix_matches() -> None:
    key = generate_api_key()
    assert extract_prefix(key.secret) == key.prefix
