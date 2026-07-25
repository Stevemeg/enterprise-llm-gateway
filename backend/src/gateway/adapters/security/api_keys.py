"""Virtual API key generation and verification (Authentication_Architecture.md §7).

Keys are ``elg_<env>_<CSPRNG>``. Only a non-secret prefix (for lookup) and a SHA-256 hash
are persisted; the full secret is shown once. Verification is timing-safe. All primitives
come from the crypto boundary (``gateway.shared.secrets``).
"""

from __future__ import annotations

from dataclasses import dataclass

from gateway.shared.auth_constants import API_KEY_PREFIX, API_KEY_PREFIX_LENGTH
from gateway.shared.secrets import generate_token, hash_secret, verify_secret


@dataclass(frozen=True, slots=True)
class GeneratedApiKey:
    """The result of issuing a key. ``secret`` is returned once and never stored."""

    secret: str
    prefix: str
    key_hash: str


def generate_api_key(environment: str = "live") -> GeneratedApiKey:
    """Generate a new virtual API key with >=256 bits of entropy."""
    secret = f"{API_KEY_PREFIX}{environment}_{generate_token(32)}"
    return GeneratedApiKey(
        secret=secret, prefix=extract_prefix(secret), key_hash=hash_secret(secret)
    )


def extract_prefix(secret: str) -> str:
    """Non-secret prefix used to look up the key record before hash verification."""
    return secret[:API_KEY_PREFIX_LENGTH]


def verify_api_key(presented_secret: str, stored_key_hash: str) -> bool:
    """Timing-safe verification of a presented key against its stored SHA-256 hash."""
    return verify_secret(presented_secret, stored_key_hash)
