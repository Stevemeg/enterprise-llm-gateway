"""Environment-backed secrets resolver (ADR-0011, realizes the SecretsResolver port).

Maps a reference like ``gateway/oidc/state-signing-key`` to an environment variable
``GATEWAY_SECRET_GATEWAY__OIDC__STATE_SIGNING_KEY``. This is the self-hosted / container-runtime
form (Kubernetes secrets, Docker secrets, and most PaaS inject secrets as env vars). A managed
KMS/Vault adapter implements the same port later without touching any caller.

Resolved values are **never logged**; only the *reference* is ever emitted in diagnostics.
"""

from __future__ import annotations

import os

from gateway.application.ports.secrets import SecretNotFoundError

_PREFIX = "GATEWAY_SECRET_"


def reference_to_env_var(reference: str) -> str:
    """``a/b-c`` -> ``GATEWAY_SECRET_A__B_C`` (deterministic, documented, reversible)."""
    normalized = reference.strip().replace("/", "__").replace("-", "_").replace(".", "_")
    return f"{_PREFIX}{normalized.upper()}"


class EnvSecretsResolver:
    """Reads secret material from the process environment."""

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else dict(os.environ)

    def try_resolve(self, reference: str) -> str | None:
        value = self._environ.get(reference_to_env_var(reference))
        return value if value else None

    def resolve(self, reference: str) -> str:
        value = self.try_resolve(reference)
        if value is None:
            # The reference is safe to name; the value is not (and does not exist here anyway).
            raise SecretNotFoundError(
                f"secret {reference!r} is not available "
                f"(expected environment variable {reference_to_env_var(reference)})"
            )
        return value


class InMemorySecretsResolver:
    """Explicit map of reference -> material. For tests and documented dev fallbacks only."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets = dict(secrets or {})

    def try_resolve(self, reference: str) -> str | None:
        return self._secrets.get(reference)

    def resolve(self, reference: str) -> str:
        value = self.try_resolve(reference)
        if value is None:
            raise SecretNotFoundError(f"secret {reference!r} is not available")
        return value
