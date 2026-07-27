"""FastAPI application factory.

Receives only the collaborators it needs (not the whole container) so the delivery
layer stays independent of ``config`` (enforced by import-linter). An optional shutdown
callback disposes owned resources (e.g., the DB engine) on app teardown.

## Slice 17: middleware ordering is a decision, not an accident

``AuthenticationMiddleware`` existed from the authentication milestone and was **never added to
this app** - implemented, unit-tested, and absent from the running middleware chain. Slice 17 adds
it, and the order matters:

Starlette's ``add_middleware`` inserts at the front of the user-middleware list, so the **last one
added is the outermost and runs first**. ``RequestContextMiddleware`` is therefore added *last*:
it must establish ``request.state.request_id`` before ``AuthenticationMiddleware`` runs, because
authentication stamps that id into its 401 bodies and its audit events. Reversing the two would
not crash - the id lookup falls back to ``"unknown"`` - which is exactly why it is pinned by a
test rather than left to a comment.

Both middlewares remain optional so tests and non-auth deployments can build the app without an
authenticator, matching the existing treatment of ``key_provider``.

## Phase 5 M3: the chain becomes four layers, and each position is forced

Outermost to innermost, with the constraint that fixes each one:

1. ``RequestContextMiddleware`` - must be first so every response below it, including the two new
   refusals, carries an ``X-Request-Id`` and appears in the access log.
2. ``RequestSizeLimitMiddleware`` - needs no identity, and authentication is not free (the API-key
   path performs a database lookup). Reading a multi-gigabyte body in order to *then* discover it
   is unauthenticated would be strictly worse than refusing it on arrival, so the cheaper,
   identity-independent gate goes first.
3. ``AuthenticationMiddleware`` - establishes the verified tenant.
4. ``RateLimitMiddleware`` - **must** be inside authentication, because its key is
   ``request.state.auth.organization_id`` and nothing else is trustworthy; and **must** be outside
   the router, because everything it protects (RBAC's query, the agent chain, the reservation, the
   provider call) lives in the route.

Positions 2 and 4 are therefore not interchangeable and not a matter of taste: swapping them would
either rate-limit on an identity that does not exist yet, or buffer an unbounded body before
finding out whether the caller is anyone. ``test_app.py`` pins the resulting order.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.application.ports.auth import AuthAuditSink, Authenticator
from gateway.application.ports.jwks import JwksPublisher
from gateway.application.ports.rate_limit import RateLimiterPort
from gateway.application.serving.inference_service import InferenceService
from gateway.delivery.http.api.inference import build_inference_router
from gateway.delivery.http.middleware.authentication import AuthenticationMiddleware
from gateway.delivery.http.middleware.body_limit import RequestSizeLimitMiddleware
from gateway.delivery.http.middleware.rate_limit import RateLimitMiddleware
from gateway.delivery.http.middleware.request_context import RequestContextMiddleware
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.delivery.http.ops.jwks import build_jwks_router
from gateway.delivery.http.ops.router import build_ops_router


def build_http_app(
    *,
    service_name: str,
    service_version: str,
    health_registry: HealthRegistry,
    key_provider: JwksPublisher | None = None,
    authenticator: Authenticator | None = None,
    audit_sink: AuthAuditSink | None = None,
    inference_service: InferenceService | None = None,
    rate_limiter: RateLimiterPort | None = None,
    max_request_bytes: int | None = None,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> FastAPI:
    """Construct the ASGI app with the middleware pipeline, ops routes, and lifespan."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if on_shutdown is not None:
            await on_shutdown()

    app = FastAPI(
        title=service_name,
        version=service_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    # Added in reverse order of execution: the LAST one added is the outermost and runs first
    # (see the module docstring for why each position is forced).
    #
    # Innermost. Added before authentication so it runs *after* it and can read the verified
    # tenant off request.state. Optional so a deployment or test without a limiter keeps the
    # pre-M3 chain rather than being handed a fabricated one.
    if rate_limiter is not None:
        app.add_middleware(RateLimitMiddleware, limiter=rate_limiter)
    if authenticator is not None and audit_sink is not None:
        app.add_middleware(AuthenticationMiddleware, authenticator=authenticator, audit=audit_sink)
    # Outside authentication: identity-independent, and refusing here avoids a database lookup
    # for a body that was never going to be accepted.
    if max_request_bytes is not None:
        app.add_middleware(RequestSizeLimitMiddleware, max_bytes=max_request_bytes)
    # Added LAST so it is outermost and runs first.
    app.add_middleware(RequestContextMiddleware)

    app.include_router(build_ops_router(health_registry))
    if inference_service is not None:
        app.include_router(build_inference_router(inference_service))
    # Public JWKS so clients can verify our tokens (ADR-0008). Optional so tests and
    # non-auth deployments can build the app without a key provider.
    if key_provider is not None:
        app.include_router(build_jwks_router(key_provider))
    return app
