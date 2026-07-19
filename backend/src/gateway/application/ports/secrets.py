"""Secrets resolution port — realizes ADR-0011 (secrets are referenced, never stored).

Configuration carries **references** (e.g. ``gateway/oidc/state-signing-key``); this port turns a
reference into the material at startup. Nothing else in the system may treat a reference as key
material — that confusion was security finding AUTH-02.

Resolution happens **once, at composition time**, so a missing secret is a start-up failure rather
than a request-time surprise (fail fast, ADR-0009).
"""

from __future__ import annotations

from typing import Protocol


class SecretNotFoundError(Exception):
    """A referenced secret could not be resolved. Callers must fail closed."""


class SecretsResolver(Protocol):
    """Resolves a secret *reference* to its material."""

    def resolve(self, reference: str) -> str:
        """Return the secret for ``reference``; raise ``SecretNotFoundError`` if unavailable."""
        ...

    def try_resolve(self, reference: str) -> str | None:
        """Return the secret, or ``None`` when absent (callers decide whether that is fatal)."""
        ...
