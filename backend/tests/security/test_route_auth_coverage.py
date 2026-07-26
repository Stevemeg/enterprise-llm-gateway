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
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.health.in_memory_circuit_breaker import InMemoryCircuitBreaker
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.in_memory_client import InMemoryProviderClient
from gateway.adapters.security.key_provider import KeyProvider
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.runner import EvaluationRunner
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.pipeline.runner import RequestPipeline
from gateway.application.ports.pricing import ModelPrice
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.providers.streaming_executor import StreamingProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.routing.catalog import ProviderDescriptor
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.application.serving.inference_service import InferenceService
from gateway.application.streaming.streaming_coordinator import StreamingCoordinator
from gateway.delivery.http.api.inference import INFERENCE_PERMISSION
from gateway.delivery.http.app import build_http_app
from gateway.delivery.http.ops.health import HealthRegistry
from tests.conftest import FixedClock
from tests.support.accounting import reservation_service

_PROVIDER = ProviderDescriptor(name="openai", model="gpt-4o")
_PRICE = ModelPrice(
    provider="openai",
    model="gpt-4o",
    input_price_per_1k=Decimal("1"),
    output_price_per_1k=Decimal("2"),
    currency="USD",
)


class _NoSleep:
    async def sleep(self, duration: Any) -> None:
        return None


class _GrantAllResolver:
    """Grants the inference permission to every principal in every tenant.

    Tenant-agnostic **on purpose**: the probe's identity is whatever a broken route invents, so a
    resolver keyed on a known principal would deny for the wrong reason and the guard would pass
    without ever being able to fail.
    """

    async def resolve(self, principal_id: UUID, organization_id: UUID) -> frozenset[str]:
        return frozenset({INFERENCE_PERMISSION})


class _AnyOrgCatalog:
    """Offers one provider to every tenant, for the same reason as ``_GrantAllResolver``."""

    async def candidates(self, organization_id: UUID) -> tuple[ProviderDescriptor, ...]:
        return (_PROVIDER,)

    async def get(self, organization_id: UUID, name: str) -> ProviderDescriptor | None:
        return _PROVIDER if name == _PROVIDER.name else None


def _permissive_inference_service() -> InferenceService:
    """An inference service in which **authentication is the only thing that can refuse**.

    Every other control is deliberately configured to allow: permissions are granted to anyone,
    a provider is offered to any tenant, the budget is unlimited (no configured limit) and the
    policy limit is the default. That is what makes the guard falsifiable - if the route stopped
    requiring an authenticated principal, an anonymous POST would run the whole path and return
    200, which is exactly the condition ``_unauthenticated_200s`` looks for.

    Nothing here is production wiring. A denying resolver would have produced 403 either way and
    the guard would have been vacuity wearing a green tick.
    """
    clock = FixedClock()
    pricing = StaticPriceTable([_PRICE])
    cache = InMemoryResponseCache(clock)
    breaker = InMemoryCircuitBreaker(clock)
    reservation = reservation_service(InMemoryBudgetLedger(), pricing)
    client = InMemoryProviderClient()
    coordinator = InferenceCoordinator(
        cache, RequestDeduplicator(), reservation, ProviderExecutor(client), breaker
    )
    streaming = StreamingCoordinator(cache, reservation, StreamingProviderExecutor(client), breaker)
    runtime = AgentRuntime(
        [PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()], clock
    )
    return InferenceService(
        RequestPipeline(
            [
                AuthorizationStage(_GrantAllResolver()),
                PolicyStage(LocalPolicyEngine()),
                AgentRoutingStage(AgentOrchestratedRoutingEngine(_AnyOrgCatalog(), runtime)),
            ]
        ),
        ReflectiveExecutor(coordinator, RetryPolicy(max_attempts=1), _NoSleep()),
        EvaluationRunner([ResponseCompletenessEvaluator()]),
        streaming,
    )


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
    """Build the app as production does, including the JWKS **and inference** routers.

    ``extra_routers`` are included **before** the app is materialized - the same way every real
    router reaches the app. FastAPI does not promise to re-expand its routing table when a
    router is added to an already-built app, so tests must not mutate a live app.

    **Slice 17: the inference service is supplied deliberately, with a *granting* resolver.**
    Until this slice the app built here had no protected route, so this guard enumerated only
    public paths and could not have failed for the one route that matters. Two things were needed
    to make it load-bearing:

    1. include the inference router, or its path is absent from the routing table entirely;
    2. wire permissions that would **allow** the request, so that a route which forgot its
       authentication check would actually reach execution and answer 200. With a denying
       resolver the endpoint would answer 403 either way, and the guard would pass for the wrong
       reason - vacuity wearing a green tick.

    No authenticator is wired: this app models "an unauthenticated caller arrives", which is
    exactly the condition the guard tests.
    """
    app = build_http_app(
        service_name="gateway-test",
        service_version="test",
        health_registry=HealthRegistry(version="test", clock=FixedClock()),
        key_provider=KeyProvider.generate(),
        inference_service=_permissive_inference_service(),
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
    """Paths that answer 200 without credentials - i.e. genuinely unprotected.

    Tries ``GET`` and, when the route does not accept it (405), retries with ``POST``. Slice 17
    added the first POST-only route; checking ``GET`` alone would have let every write endpoint
    past this guard forever, since a POST-only path answers 405 to a GET and 405 is not 200.
    """
    client = _client(app)
    offenders: list[str] = []
    for path in sorted(_all_paths(app) - set(PUBLIC_ROUTES)):
        if "{" in path:  # templated paths need fixtures; covered by their own tests
            continue
        try:
            response = client.get(path)
            if response.status_code == 405:
                response = client.post(path, json={"prompt": "unauthenticated probe"})
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
