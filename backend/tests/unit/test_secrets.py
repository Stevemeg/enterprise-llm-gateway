"""Tests for the crypto boundary: randomness, hashing, timing-safe compare, zeroize."""

from __future__ import annotations

import pytest

from gateway.shared.secrets import (
    constant_time_equals,
    generate_token,
    hash_secret,
    sha256_hex,
    verify_secret,
    zeroize,
)


def test_generate_token_is_unique_and_urlsafe() -> None:
    tokens = {generate_token() for _ in range(1000)}
    assert len(tokens) == 1000  # no collisions from CSPRNG
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert all(set(token) <= allowed for token in tokens)


def test_generate_token_enforces_entropy_floor() -> None:
    with pytest.raises(ValueError, match="entropy"):
        generate_token(8)


def test_sha256_known_vector() -> None:
    # SHA-256("abc")
    assert sha256_hex("abc") == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_constant_time_equals() -> None:
    assert constant_time_equals("same-value", "same-value") is True
    assert constant_time_equals("a", "b") is False
    assert constant_time_equals("short", "a-much-longer-value") is False


def test_verify_secret_roundtrip() -> None:
    stored = hash_secret("elg_live_supersecret")
    assert verify_secret("elg_live_supersecret", stored) is True
    assert verify_secret("wrong", stored) is False


def test_zeroize_wipes_buffer() -> None:
    buffer = bytearray(b"topsecret")
    zeroize(buffer)
    assert buffer == bytearray(len(b"topsecret"))
    assert set(buffer) == {0}
