"""RSA signing-key material and generation (Cryptographic_Architecture.md §1).

A ``SigningKey`` holds a private+public PEM pair identified by ``kid``. Public-only
``VerificationKey`` is what verifiers and JWKS use. Private keys come from the secrets
manager in production; this module also generates keypairs (rotation, tests).
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_RSA_KEY_SIZE = 2048
_PUBLIC_EXPONENT = 65537


@dataclass(frozen=True, slots=True)
class VerificationKey:
    """A public key used to verify JWT signatures."""

    kid: str
    public_pem: str


@dataclass(frozen=True, slots=True)
class SigningKey:
    """A private+public RSA key pair used to sign JWTs."""

    kid: str
    private_pem: str
    public_pem: str

    def to_verification_key(self) -> VerificationKey:
        return VerificationKey(kid=self.kid, public_pem=self.public_pem)


def generate_signing_key(kid: str, *, key_size: int = _RSA_KEY_SIZE) -> SigningKey:
    """Generate a new RSA signing key (rotation / bootstrap / tests)."""
    private_key = rsa.generate_private_key(public_exponent=_PUBLIC_EXPONENT, key_size=key_size)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return SigningKey(kid=kid, private_pem=private_pem, public_pem=public_pem)


def derive_public_pem(private_pem: str) -> str:
    """Derive the public PEM from a private PEM so the pair can never drift apart."""
    private_key = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
