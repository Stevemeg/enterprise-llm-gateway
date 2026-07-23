"""The single audited cryptographic boundary (Cryptographic_Architecture.md).

ALL low-level crypto lives here: CSPRNG token generation, SHA-256 hashing, timing-safe
comparison, and best-effort zeroization. Enforced by import-linter — no other module may
import ``secrets``, ``hmac``, or ``hashlib`` directly. (Asymmetric signing lives in
``adapters/security``.)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_MIN_TOKEN_BYTES = 16
_DEFAULT_TOKEN_BYTES = 32


def generate_token(n_bytes: int = _DEFAULT_TOKEN_BYTES) -> str:
    """Return a URL-safe CSPRNG token. Rejects entropy below the security floor."""
    if n_bytes < _MIN_TOKEN_BYTES:
        raise ValueError(f"token entropy must be >= {_MIN_TOKEN_BYTES} bytes")
    return secrets.token_urlsafe(n_bytes)


def generate_hex(n_bytes: int = _DEFAULT_TOKEN_BYTES) -> str:
    """Return a CSPRNG hex token (e.g., for a JWT ``jti``)."""
    if n_bytes < _MIN_TOKEN_BYTES:
        raise ValueError(f"token entropy must be >= {_MIN_TOKEN_BYTES} bytes")
    return secrets.token_hex(n_bytes)


def sha256_hex(value: str) -> str:
    """SHA-256 of a UTF-8 string, hex-encoded."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: str) -> bytes:
    """SHA-256 of a UTF-8 string, as the raw 32-byte digest.

    Used where the digest is stored/compared as bytes rather than displayed (e.g. a cache
    identity keyed against a ``bytea`` column) - ``sha256_hex`` exists for the display/storage
    case, this one for the binary-identity case, both over the same sanctioned boundary.
    """
    return hashlib.sha256(value.encode("utf-8")).digest()


def hash_secret(secret: str) -> str:
    """Hash a high-entropy secret (API key / refresh token) for storage.

    A fast hash is appropriate: these secrets are high-entropy random values, not
    human passwords (which would use Argon2id — Cryptographic_Architecture.md §3).
    """
    return sha256_hex(secret)


def constant_time_equals(left: str, right: str) -> bool:
    """Timing-safe string comparison (no early-exit information leak)."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def verify_secret(presented: str, stored_hash_hex: str) -> bool:
    """Timing-safe check of a presented secret against a stored SHA-256 hex hash."""
    return constant_time_equals(sha256_hex(presented), stored_hash_hex)


def zeroize(buffer: bytearray) -> None:
    """Best-effort wipe of a mutable secret buffer, where the runtime permits.

    Only works on mutable buffers (``bytearray``); Python ``str``/``bytes`` are immutable
    and cannot be wiped in place — hold sensitive material in ``bytearray`` when wiping matters.
    """
    for index in range(len(buffer)):
        buffer[index] = 0


def sha256_b64url(value: str) -> str:
    """Base64url-encoded (unpadded) SHA-256 of ``value``.

    Used for the PKCE ``S256`` code challenge: BASE64URL(SHA256(ASCII(code_verifier)))
    with padding stripped, per RFC 7636 §4.2.
    """
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def hmac_sha256_hex(key: str, message: str) -> str:
    """Hex HMAC-SHA256 of ``message`` under ``key`` (integrity tag, not encryption).

    Used to bind the tenant hint into the OIDC ``state`` so the callback can resolve the
    organization *before* touching the database, without trusting the browser (ADR-0015).
    """
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
