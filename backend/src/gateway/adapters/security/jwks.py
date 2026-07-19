"""JWKS document construction (Authentication_Architecture.md §10, Crypto §1.2).

Publishes RSA public keys as a JWKS set so services verify gateway JWTs without the
signing secret. During rotation the set carries current + previous keys.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from gateway.adapters.security.keys import VerificationKey


def _b64url_uint(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode("ascii")


def _to_jwk(key: VerificationKey) -> dict[str, str]:
    public_key = load_pem_public_key(key.public_pem.encode("utf-8"))
    if not isinstance(public_key, RSAPublicKey):
        raise ValueError(f"key {key.kid!r} is not an RSA public key")
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key.kid,
        "n": _b64url_uint(numbers.n),
        "e": _b64url_uint(numbers.e),
    }


def build_jwks(keys: Sequence[VerificationKey]) -> dict[str, Any]:
    """Build a JWKS document from public verification keys."""
    return {"keys": [_to_jwk(key) for key in keys]}
