"""Signing-key provider with rotation + JWKS (Cryptographic_Architecture.md §1/§11).

Holds the current signing key plus previous public keys so tokens signed by an outgoing
key still validate during the rotation grace window. In production the current key is
sourced from the secrets manager (``SecretsPort``, wired later); ``generate`` bootstraps
one for local/self-host/dev.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gateway.adapters.security.jwks import build_jwks
from gateway.adapters.security.keys import (
    SigningKey,
    VerificationKey,
    derive_public_pem,
    generate_signing_key,
)


@dataclass(frozen=True, slots=True)
class KeyProvider:
    current: SigningKey
    previous: tuple[VerificationKey, ...] = ()

    @classmethod
    def generate(cls, kid: str = "gateway-1") -> KeyProvider:
        """Bootstrap a provider with a freshly generated signing key.

        **Development and tests only.** Generating keys per process means a restart invalidates
        every outstanding token and replicas disagree on JWKS (security finding AUTH-01), so
        production must use :meth:`from_pem` with material from the secrets manager.
        """
        return cls(current=generate_signing_key(kid))

    @classmethod
    def from_pem(
        cls,
        *,
        kid: str,
        private_pem: str,
        previous: tuple[tuple[str, str], ...] = (),
    ) -> KeyProvider:
        """Build a provider from managed key material (ADR-0011).

        ``previous`` is a tuple of ``(kid, public_pem)`` for keys still inside their rotation
        overlap window: tokens they signed keep verifying until the window closes, which is what
        makes rotation non-disruptive. The public key is derived from the private one so the two
        can never drift out of sync.
        """
        current = SigningKey(
            kid=kid, private_pem=private_pem, public_pem=derive_public_pem(private_pem)
        )
        retained = tuple(VerificationKey(kid=k, public_pem=pem) for k, pem in previous)
        return cls(current=current, previous=retained)

    def current_signing_key(self) -> SigningKey:
        return self.current

    def verification_keys(self) -> dict[str, str]:
        """Map of kid -> public PEM for the current + previous keys (rotation)."""
        keys = {self.current.kid: self.current.public_pem}
        for key in self.previous:
            keys[key.kid] = key.public_pem
        return keys

    def jwks(self) -> dict[str, Any]:
        return build_jwks([self.current.to_verification_key(), *self.previous])

    def rotate(self, new_kid: str) -> KeyProvider:
        """Return a provider with a new signing key; the old public key is retained."""
        retained = (self.current.to_verification_key(), *self.previous)
        return KeyProvider(current=generate_signing_key(new_kid), previous=retained)
