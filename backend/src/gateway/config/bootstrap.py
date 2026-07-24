"""Application bootstrap — the process entrypoint (Guide §5/§10).

``create_app`` is a factory used by the ASGI server:

    uvicorn --factory gateway.config.bootstrap:create_app

It loads+validates settings (fail-fast), builds the container (composition root), and
constructs the HTTP app bound to the wired collaborators, disposing the DB pool on
shutdown.
"""

from __future__ import annotations

from fastapi import FastAPI

from gateway.config.container import Container
from gateway.config.settings import Settings, load_settings
from gateway.delivery.http.app import build_http_app


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the ASGI application. Pass ``settings`` in tests; else load from env."""
    resolved = settings if settings is not None else load_settings()
    container = Container.create(resolved)
    app = build_http_app(
        service_name=resolved.app_name,
        service_version=resolved.service_version,
        health_registry=container.health,
        key_provider=container.key_provider,
        # Slice 17: authentication now executes, and the inference path is reachable.
        authenticator=container.authenticator,
        audit_sink=container.audit_sink,
        inference_service=container.inference_service,
        on_shutdown=container.dispose,
    )
    app.state.container = container
    return app
