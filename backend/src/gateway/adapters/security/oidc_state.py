"""OIDC ``state`` signing and PKCE generation (ADR-0015).

The callback arrives with no tenant context, but ``oidc_login_state`` is RLS-scoped — so the
organization must be resolved *before* the first database read. We therefore bind the org into
the ``state`` parameter and protect it with an HMAC tag:

    state = "<b64url(org_id.random)>.<hmac-sha256 tag>"

On callback the tag is verified **first** (constant-time). Only then is the org trusted enough to
set the RLS context and consume the row. A tampered or truncated state never reaches the database.
The random half is what is hashed into ``state_hash``; the raw state is never stored.

All primitives go through ``shared.secrets`` (the single crypto boundary).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from uuid import UUID

from gateway.shared.secrets import (
    constant_time_equals,
    generate_token,
    hmac_sha256_hex,
    sha256_b64url,
    sha256_hex,
)

_SEPARATOR = "."
_PKCE_VERIFIER_BYTES = 32  # -> 43-char base64url verifier (RFC 7636 allows 43..128)


class InvalidStateError(Exception):
    """Raised when a presented ``state`` is malformed or fails HMAC verification."""


@dataclass(frozen=True, slots=True)
class ParsedState:
    organization_id: UUID
    random_part: str

    @property
    def state_hash(self) -> str:
        """Hex SHA-256 of the random half — the key stored in ``oidc_login_state``."""
        return sha256_hex(self.random_part)


def _b64url_encode(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


class StateSigner:
    """Creates and verifies tenant-bound, integrity-protected ``state`` values."""

    def __init__(self, signing_key: str) -> None:
        if not signing_key:
            raise ValueError("state signing key must not be empty")
        self._key = signing_key

    def issue(self, organization_id: UUID) -> tuple[str, ParsedState]:
        """Return ``(state_to_send, parsed)`` for a fresh login attempt."""
        random_part = generate_token()
        payload = _b64url_encode(f"{organization_id}{_SEPARATOR}{random_part}")
        state = f"{payload}{_SEPARATOR}{hmac_sha256_hex(self._key, payload)}"
        return state, ParsedState(organization_id=organization_id, random_part=random_part)

    def verify(self, state: str) -> ParsedState:
        """Verify the HMAC and decode the org. Raises ``InvalidStateError`` on any problem."""
        payload, separator, tag = state.rpartition(_SEPARATOR)
        if not separator or not payload or not tag:
            raise InvalidStateError("state is malformed")
        if not constant_time_equals(hmac_sha256_hex(self._key, payload), tag):
            raise InvalidStateError("state signature verification failed")
        try:
            decoded = _b64url_decode(payload)
            org_text, inner_separator, random_part = decoded.partition(_SEPARATOR)
            if not inner_separator or not random_part:
                raise InvalidStateError("state payload is malformed")
            organization_id = UUID(org_text)
        except InvalidStateError:
            raise
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidStateError("state payload is malformed") from exc
        return ParsedState(organization_id=organization_id, random_part=random_part)


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE ``S256`` (RFC 7636)."""
    verifier = generate_token(_PKCE_VERIFIER_BYTES)
    return verifier, sha256_b64url(verifier)
