"""Public JWKS endpoint: `GET /.well-known/jwks.json` (ADR-0008, FR-092/093).

Publishes the **public** halves of the gateway's signing keys so clients and downstream services
can verify issued access tokens. Deliberately public and unauthenticated - verifying a token
must not itself require a token.

Two invariants matter here:
  * **Public keys only.** The payload comes from ``KeyProvider.jwks()``, which is built from
    verification keys; no private material can reach this route.
  * **Never generates keys.** The provider is resolved once at composition time. A request must
    not be able to trigger key creation, or an attacker could churn keys by hammering the
    endpoint (and per AUTH-01 generated keys are a dev-only path anyway).

The response includes the current key plus any previous keys still inside the rotation overlap
window, which is what lets rotation happen without invalidating outstanding tokens.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from gateway.application.ports.jwks import JwksPublisher

JWKS_PATH = "/.well-known/jwks.json"


def build_jwks_router(key_provider: JwksPublisher) -> APIRouter:
    """Router exposing the public JWKS. ``key_provider`` is already-resolved; never regenerated."""
    router = APIRouter(tags=["Auth"])

    @router.get(JWKS_PATH, summary="Public JSON Web Key Set")
    async def jwks() -> dict[str, Any]:
        return key_provider.jwks()

    return router
