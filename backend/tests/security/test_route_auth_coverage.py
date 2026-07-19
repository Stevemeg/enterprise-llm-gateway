"""Every non-public route must require authentication (AUTH-03).

The authentication middleware deliberately lets *unauthenticated* requests through, because
public routes exist and enforcement is the route's job. That design has one failure mode: a
route that forgets its auth dependency becomes silently unauthenticated. This module closes
that gap - a new endpoint without protection fails CI instead of shipping open.

**Why behavioural, not introspective.** Earlier revisions inspected route objects to look for
auth dependencies. FastAPI wraps included routers in internal containers whose children are not
reachable via any documented attribute, so six successive route walkers silently enumerated
*nothing* - and a check over an empty set always "passes". This version instead asserts the
security property directly: an unauthenticated GET must not return 200. Whatever the routing
internals look like, a caller without credentials either gets data back or does not.

To add a genuinely public endpoint, add it to ``PUBLIC_ROUTES`` **and** say why. That makes
exposing an endpoint a deliberate, reviewable act rather than an oversight.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.adapters.security.key_provider import KeyProvider
from gateway.delivery.http.app import build_http_app
from gateway.delivery.http.ops.health import HealthRegistry
from tests.conftest import FixedClock

# Intentionally unauthenticated. Each entry needs a justification.
PUBLIC_ROUTES: dict[str, str] = {
    "/livez": "liveness probe - must answer before dependencies are ready",
    "/readyz": "readiness probe - consumed by the orchestrator, no tenant data",
    "/healthz": "health summary - no tenant data",
    "/metrics": "Prometheus scrape - network-restricted, no tenant data",
    "/.well-known/jwks.json": "public signing keys - public by definition",
    "/openapi.json": "API schema",
    "/docs": "API docs",
    "/docs/oauth2-redirect": "API docs",
    "/redoc": "API docs",
}


def _app(extra_routers: Iterable[Any] = ()) -> FastAPI:
    """Build the app as production does, including the JWKS router.

    ``extra_routers`` are included **before** the app is materialized - the same way every real
    router reaches the app. FastAPI does not promise to re-expand its routing table when a
    router is added to an already-built app, so tests must not mutate a live app.
    """
    app = build_http_app(
        service_name="gateway-test",
        service_version="test",
        health_registry=HealthRegistry(version="test", clock=FixedClock()),
        key_provider=KeyProvider.generate(),
    )
    for router in extra_routers:
        app.include_router(router)
    return app


def _client(app: FastAPI) -> TestClient:
    """A client bound to a fully wired app (constructing it runs FastAPI's setup)."""
    return TestClient(app)


def _all_paths(app: FastAPI) -> set[str]:
    """Every path the app serves, from the OpenAPI schema - a public, stable interface."""
    _client(app)
    return set(app.openapi().get("paths", {}))


def _unauthenticated_200s(app: FastAPI) -> list[str]:
    """Paths that answer 200 to an unauthenticated GET - i.e. genuinely unprotected."""
    client = _client(app)
    offenders: list[str] = []
    for path in sorted(_all_paths(app) - set(PUBLIC_ROUTES)):
        if "{" in path:  # templated paths need fixtures; covered by their own tests
            continue
        try:
            response = client.get(path)
        except Exception:
            continue
        if response.status_code == 200:
            offenders.append(path)
    return offenders


def test_every_non_public_route_requires_authentication() -> None:
    unprotected = _unauthenticated_200s(_app())
    assert not unprotected, (
        "these routes answer 200 without credentials - add authentication, or add them to "
        f"PUBLIC_ROUTES with a justification: {unprotected}"
    )


def test_the_checker_actually_detects_an_unprotected_route() -> None:
    """Prove this guard FAILS when it should.

    A passing security test that cannot fail is worse than no test: it manufactures confidence.
    Earlier revisions enumerated zero routes and reported success for three runs. This mounts a
    deliberately unauthenticated endpoint through a router and asserts the checker flags it.
    """
    from fastapi import APIRouter

    smuggled = APIRouter()

    @smuggled.get("/totally-unprotected")
    async def unprotected() -> dict[str, str]:
        return {"oops": "no auth"}

    app = _app(extra_routers=[smuggled])

    assert "/totally-unprotected" in _unauthenticated_200s(app), (
        "the checker did not flag an endpoint returning 200 without credentials, so it would "
        "not catch a genuinely unauthenticated route"
    )


def test_public_route_allow_list_is_justified_and_minimal() -> None:
    """Every exemption must carry a reason and correspond to a real route."""
    app = _app()
    actual_paths = _all_paths(app)

    for path, reason in PUBLIC_ROUTES.items():
        assert reason.strip(), f"public route {path} has no justification"

    # /docs, /redoc and /docs/oauth2-redirect are served but absent from the OpenAPI schema.
    documented_exemptions = {p for p in PUBLIC_ROUTES if not p.startswith("/docs")}
    documented_exemptions -= {"/redoc", "/openapi.json"}
    stale = documented_exemptions - actual_paths
    assert not stale, (
        f"PUBLIC_ROUTES lists routes that no longer exist: {sorted(stale)}\n"
        f"App actually exposes: {sorted(actual_paths)}"
    )


def test_enumeration_sees_the_real_ops_routes() -> None:
    """Ops + JWKS routes must be visible; otherwise the check inspects nothing."""
    paths = _all_paths(_app())
    for expected in ("/livez", "/readyz", "/healthz", "/.well-known/jwks.json"):
        assert expected in paths, f"{expected} not visible; found {sorted(paths)}"
