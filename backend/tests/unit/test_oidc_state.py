"""OIDC state signing + PKCE (ADR-0015).

The signed ``state`` is what lets the callback resolve a tenant *before* touching the RLS-scoped
store, so forging or tampering with it must be impossible without the signing key.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from gateway.adapters.security.oidc_state import (
    InvalidStateError,
    StateSigner,
    generate_pkce_pair,
)
from gateway.shared.secrets import sha256_b64url, sha256_hex

_KEY = "unit-test-state-signing-key"


def test_issue_then_verify_roundtrips_the_organization() -> None:
    signer = StateSigner(_KEY)
    org = uuid4()

    state, issued = signer.issue(org)
    parsed = signer.verify(state)

    assert parsed.organization_id == org
    assert parsed.random_part == issued.random_part
    assert parsed.state_hash == sha256_hex(issued.random_part)


def test_raw_state_is_not_recoverable_from_the_stored_hash() -> None:
    signer = StateSigner(_KEY)
    state, issued = signer.issue(uuid4())
    assert issued.random_part not in issued.state_hash
    assert issued.state_hash != issued.random_part
    assert state.count(".") == 1, "state is payload.tag; b64url payload contains no dots"


def test_tampered_payload_is_rejected() -> None:
    signer = StateSigner(_KEY)
    state, _ = signer.issue(uuid4())
    payload, _, tag = state.rpartition(".")
    forged = f"{payload}X.{tag}"

    with pytest.raises(InvalidStateError):
        signer.verify(forged)


def test_swapped_organization_is_rejected() -> None:
    """An attacker re-pointing the state at another tenant must fail the HMAC."""
    signer = StateSigner(_KEY)
    victim_state, _ = signer.issue(uuid4())
    attacker_state, _ = signer.issue(uuid4())
    victim_payload, _, _ = victim_state.rpartition(".")
    _, _, attacker_tag = attacker_state.rpartition(".")

    with pytest.raises(InvalidStateError):
        signer.verify(f"{victim_payload}.{attacker_tag}")


def test_state_signed_with_another_key_is_rejected() -> None:
    state, _ = StateSigner("some-other-key").issue(uuid4())

    with pytest.raises(InvalidStateError):
        StateSigner(_KEY).verify(state)


@pytest.mark.parametrize("bad", ["", ".", "no-separator", "abc.", ".abc"])
def test_malformed_state_is_rejected(bad: str) -> None:
    with pytest.raises(InvalidStateError):
        StateSigner(_KEY).verify(bad)


def test_empty_signing_key_is_refused() -> None:
    with pytest.raises(ValueError, match="signing key"):
        StateSigner("")


def test_pkce_challenge_is_s256_of_the_verifier() -> None:
    verifier, challenge = generate_pkce_pair()

    assert challenge == sha256_b64url(verifier)
    assert "=" not in challenge, "S256 challenge must be unpadded base64url (RFC 7636)"
    assert 43 <= len(verifier) <= 128


def test_pkce_pairs_are_unique_per_login() -> None:
    first, _ = generate_pkce_pair()
    second, _ = generate_pkce_pair()
    assert first != second
