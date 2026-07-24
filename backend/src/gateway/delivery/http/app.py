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
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.application.ports.auth import AuthAuditSink, Authenticator
from gateway.application.ports.jwks import JwksPublisher
from gateway.application.serving.inference_service import InferenceService
from gateway.delivery.http.api.inference import build_inference_router
from gateway.delivery.http.middleware.authentication import AuthenticationMiddleware
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
    # Added FIRST so it ends up INNER: request context must already be established when
    # authentication runs (see the module docstring).
    if authenticator is not None and audit_sink is not None:
        app.add_middleware(AuthenticationMiddleware, authenticator=authenticator, audit=audit_sink)
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
