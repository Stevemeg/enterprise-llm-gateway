"""JWKS publication port (ADR-0008).

The delivery layer must publish the public key set without importing the key provider, because
that adapter transitively imports ``cryptography`` and the crypto-boundary contract forbids
asymmetric crypto anywhere outside adapters (import-linter enforced).

This Protocol is the seam: delivery depends on the *shape* (``jwks()`` returns a JWKS document),
the composition root injects ``KeyProvider``, which satisfies it structurally. No crypto import
crosses the boundary.
"""

from __future__ import annotations

from typing import Any, Protocol


class JwksPublisher(Protocol):
    """Supplies the public JSON Web Key Set. Public keys only; never generates keys."""

    def jwks(self) -> dict[str, Any]: ...
