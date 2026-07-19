"""FastAPI application factory.

Receives only the collaborators it needs (not the whole container) so the delivery
layer stays independent of ``config`` (enforced by import-linter). An optional shutdown
callback disposes owned resources (e.g., the DB engine) on app teardown.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gateway.application.ports.jwks import JwksPublisher
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
    app.add_middleware(RequestContextMiddleware)
    app.include_router(build_ops_router(health_registry))
    # Public JWKS so clients can verify our tokens (ADR-0008). Optional so tests and
    # non-auth deployments can build the app without a key provider.
    if key_provider is not None:
        app.include_router(build_jwks_router(key_provider))
    return app
