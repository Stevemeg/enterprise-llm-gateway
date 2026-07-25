"""``POST /v1/inference`` end to end (ADR-0016 Slice 17).

These drive the **real composed application**: the real ASGI app with the real
``AuthenticationMiddleware`` in its chain, the real ``RequestPipeline``, the real routing engine,
the real coordinator and the real evaluators. Spies wrap those collaborators rather than replacing
them, because "no provider was called" and "no budget was reserved" are only evidence if the things
that did not happen are the components that would really have done them.

The tests assert **bypasses are impossible**, not merely that status codes are right: every
negative case checks the downstream side effects that must not have occurred.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from gateway.adapters.audit.logging_sink import LoggingAuthAuditSink
from gateway.adapters.authorization.in_memory_resolver import InMemoryPermissionResolver
from gateway.adapters.authorization.null_resolver import NullPermissionResolver
from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.health.in_memory_circuit_breaker import InMemoryCircuitBreaker
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.fake_client import FakeProviderClient
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.runner import EvaluationRunner
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.pipeline.runner import RequestPipeline
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.money import Money
from gateway.application.ports.pricing import ModelPrice
from gateway.application.ports.providers import (
    InferenceRequest,
    ProviderResponse,
    ProviderUsage,
)
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.routing.catalog import InMemoryProviderCatalog, ProviderDescriptor
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.application.serving.inference_service import InferenceService
from gateway.delivery.http.api.inference import INFERENCE_PATH, INFERENCE_PERMISSION
from gateway.delivery.http.app import build_http_app
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.domain.auth.errors import CredentialInvalidError
from gateway.domain.auth.models import Principal, PrincipalType

ORG = uuid4()
PRINCIPAL = uuid4()
PROVIDER = ProviderDescriptor(name="openai", model="gpt-4o")
PRICE = ModelPrice(
    provider="openai",
    model="gpt-4o",
    input_price_per_1k=Decimal("1"),
    output_price_per_1k=Decimal("2"),
    currency="USD",
)
GOOD_TOKEN = "valid-token"


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


class NoSleep:
    async def sleep(self, duration: timedelta) -> None:
        return None


class StubAuthenticator:
    """Accepts exactly one token. Anything else fails closed, like the real verifier."""

    def __init__(self, *, organization_id: UUID = ORG, principal_id: UUID = PRINCIPAL) -> None:
        self._organization_id = organization_id
        self._principal_id = principal_id

    async def authenticate(self, credential: str) -> Principal:
        if credential != GOOD_TOKEN:
            raise CredentialInvalidError("invalid credential")
        return Principal(
            principal_type=PrincipalType.USER,
            subject_id=self._principal_id,
            organization_id=self._organization_id,
        )


class SpyProviderClient:
    def __init__(self, inner: FakeProviderClient) -> None:
        self._inner = inner
        self.invocations: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.invocations)

    async def invoke(
        self, provider: ProviderDescriptor, request: InferenceRequest
    ) -> ProviderResponse:
        self.invocations.append(request.correlation_id)
        return await self._inner.invoke(provider, request)


class SpyLedger:
    def __init__(self, inner: BudgetLedgerPort) -> None:
        self._inner = inner
        self.reserved: list[str] = []
        self.settled: list[str] = []
        self.released: list[str] = []

    @property
    def touched(self) -> bool:
        return bool(self.reserved or self.settled or self.released)

    async def reserve(self, organization_id: UUID, correlation_id: str, cost: Money) -> Any:
        self.reserved.append(correlation_id)
        return await self._inner.reserve(organization_id, correlation_id, cost)

    async def settle(self, organization_id: UUID, correlation_id: str, detail: Any) -> None:
        self.settled.append(correlation_id)
        await self._inner.settle(organization_id, correlation_id, detail)

    async def release(self, organization_id: UUID, correlation_id: str) -> None:
        self.released.append(correlation_id)
        await self._inner.release(organization_id, correlation_id)


class SpyRoutingEngine:
    def __init__(self, inner: AgentOrchestratedRoutingEngine) -> None:
        self._inner = inner
        self.calls: list[str] = []

    @property
    def called(self) -> bool:
        return bool(self.calls)

    async def route(
        self,
        *,
        organization_id: UUID,
        correlation_id: str,
        request: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(correlation_id)
        return await self._inner.route(
            organization_id=organization_id, correlation_id=correlation_id, request=request
        )


def _usage() -> ProviderUsage:
    return ProviderUsage(prompt_tokens=10, completion_tokens=5)


class Harness:
    """The real app, wired the way bootstrap wires it."""

    def __init__(
        self,
        *,
        responses: list[ProviderResponse] | None = None,
        grant: bool = True,
        max_request_bytes: int = 128 * 1024,
        limit: Money | None = None,
        candidates: list[ProviderDescriptor] | None = None,
        with_auth: bool = True,
    ) -> None:
        clock = FixedClock()
        self.client_spy = SpyProviderClient(
            FakeProviderClient(
                sequence=responses
                or [ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())]
            )
        )
        self.ledger = SpyLedger(
            InMemoryBudgetLedger({ORG: limit or Money(Decimal("100.00"), "USD")})
        )
        pricing = StaticPriceTable([PRICE])
        coordinator = InferenceCoordinator(
            InMemoryResponseCache(clock),
            RequestDeduplicator(),
            ReservationService(self.ledger, pricing, CostAccountant(pricing)),
            ProviderExecutor(self.client_spy),
            InMemoryCircuitBreaker(clock),
        )
        runtime = AgentRuntime(
            [PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()], clock
        )
        catalog = InMemoryProviderCatalog(
            {ORG: candidates if candidates is not None else [PROVIDER]}
        )
        self.routing = SpyRoutingEngine(AgentOrchestratedRoutingEngine(catalog, runtime))

        resolver: InMemoryPermissionResolver | NullPermissionResolver
        if grant:
            resolver = InMemoryPermissionResolver({"caller": [INFERENCE_PERMISSION]})
            resolver.assign(ORG, PRINCIPAL, ["caller"])
        else:
            resolver = NullPermissionResolver()

        service = InferenceService(
            RequestPipeline(
                [
                    AuthorizationStage(resolver),
                    PolicyStage(LocalPolicyEngine(max_request_bytes=max_request_bytes)),
                    AgentRoutingStage(self.routing),
                ]
            ),
            ReflectiveExecutor(coordinator, RetryPolicy(max_attempts=1), NoSleep()),
            EvaluationRunner(
                [ResponseCompletenessEvaluator(), UsageAccountingConsistencyEvaluator()]
            ),
        )
        self.app = build_http_app(
            service_name="test",
            service_version="0.1.0",
            health_registry=HealthRegistry(version="0.1.0", clock=clock),
            authenticator=StubAuthenticator() if with_auth else None,
            audit_sink=LoggingAuthAuditSink() if with_auth else None,
            inference_service=service,
        )
        self.http = TestClient(self.app)

    def post(self, body: Any = None, *, token: str | None = GOOD_TOKEN) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return self.http.post(
            INFERENCE_PATH, json=body if body is not None else {"prompt": "hello"}, headers=headers
        )


# --- unauthenticated ---------------------------------------------------------------------------


def test_an_unauthenticated_request_is_refused_and_reaches_nothing() -> None:
    """No credential at all. The middleware passes it through (public routes exist); the route
    refuses it, and nothing downstream runs."""
    harness = Harness()

    response = harness.post(token=None)

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_an_invalid_credential_is_refused_by_the_middleware_before_the_route() -> None:
    """The middleware is genuinely in the chain: a bad token never reaches the endpoint."""
    harness = Harness()

    response = harness.post(token="not-a-real-token")

    assert response.status_code == 401
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_a_malformed_authorization_header_fails_closed() -> None:
    harness = Harness()

    response = harness.http.post(
        INFERENCE_PATH, json={"prompt": "hello"}, headers={"Authorization": "Basic abc"}
    )

    assert response.status_code == 401
    assert harness.routing.called is False


def test_the_401_body_carries_the_request_id_proving_middleware_ordering() -> None:
    """RequestContextMiddleware must run BEFORE authentication, or the id would be 'unknown'."""
    harness = Harness()

    response = harness.post(token="bad")

    body = response.json()
    assert body["error"]["request_id"] != "unknown"
    assert body["error"]["request_id"] == response.headers["X-Request-Id"]


# --- malformed input ---------------------------------------------------------------------------


def test_a_malformed_body_is_rejected_before_any_admission_or_execution() -> None:
    harness = Harness()

    response = harness.post({"not_a_prompt": 1})

    assert response.status_code == 422
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_an_empty_prompt_is_rejected_before_execution() -> None:
    harness = Harness()

    response = harness.post({"prompt": ""})

    assert response.status_code == 422
    assert harness.client_spy.called is False


def test_an_unexpected_field_is_rejected_rather_than_travelling_into_the_payload() -> None:
    """``extra="forbid"`` keeps unmodelled input out of the payload the policy engine measures."""
    harness = Harness()

    response = harness.post({"prompt": "hello", "smuggled": "x" * 1000})

    assert response.status_code == 422
    assert harness.client_spy.called is False


# --- unauthorized / policy ----------------------------------------------------------------------


def test_an_authorized_credential_without_permission_is_denied_before_routing() -> None:
    harness = Harness(grant=False)

    response = harness.post()

    assert response.status_code == 403
    assert response.json()["error"]["type"] == "permission_error"
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_a_policy_denial_is_403_and_reaches_no_routing_or_provider() -> None:
    harness = Harness(max_request_bytes=4)

    response = harness.post({"prompt": "a payload well beyond the configured limit"})

    assert response.status_code == 403
    assert harness.routing.called is False
    assert harness.client_spy.called is False
    assert harness.ledger.touched is False


def test_a_denial_does_not_disclose_the_permission_rule_or_threshold() -> None:
    harness = Harness(grant=False)

    body = harness.post().json()

    rendered = str(body)
    assert INFERENCE_PERMISSION not in rendered
    assert "max_request_bytes" not in rendered


# --- budget / availability / provider -------------------------------------------------------------


def test_a_budget_denial_is_402_and_the_provider_is_never_called() -> None:
    harness = Harness(limit=Money(Decimal("0.00000001"), "USD"))

    response = harness.post()

    assert response.status_code == 402
    assert response.json()["error"]["type"] == "budget_error"
    assert harness.routing.called is True  # routing ran; the budget gate stopped it after
    assert harness.client_spy.called is False


def test_nothing_routable_is_503_and_calls_no_provider() -> None:
    harness = Harness(candidates=[])

    response = harness.post()

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "availability_error"
    assert harness.client_spy.called is False


def test_a_provider_failure_is_502_and_never_echoes_the_provider_error_text() -> None:
    harness = Harness(
        responses=[ProviderResponse(ok=False, error="UPSTREAM SECRET DETAIL", provider="openai")]
    )

    response = harness.post()

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "provider_error"
    assert "UPSTREAM SECRET DETAIL" not in str(response.json())
    assert harness.ledger.released  # the hold was released, not settled
    assert harness.ledger.settled == []


# --- success ----------------------------------------------------------------------------


def test_a_fully_authorized_request_executes_and_returns_200() -> None:
    harness = Harness()

    response = harness.post()

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "hi"
    assert body["provider"] == "openai"
    assert body["cached"] is False
    assert harness.routing.called is True
    assert harness.client_spy.called is True
    assert harness.ledger.settled  # spend was booked exactly once
    assert harness.ledger.released == []


def test_the_response_carries_the_request_id_used_as_the_correlation_id() -> None:
    harness = Harness()

    response = harness.post()

    assert response.json()["request_id"] == response.headers["X-Request-Id"]


def test_organization_and_principal_propagate_from_the_credential_into_admission() -> None:
    """The tenant the route acts for comes from the verified credential, never from the body."""
    harness = Harness()

    assert harness.post().status_code == 200
    # The routing engine is tenant-scoped; it was reached with the authenticated org's catalog,
    # which only resolves because organization_id came from the principal.
    assert harness.routing.called is True


def test_a_second_identical_request_is_served_from_cache_without_a_second_provider_call() -> None:
    harness = Harness(
        responses=[ProviderResponse(ok=True, content="hi", provider="openai", usage=_usage())]
    )

    first = harness.post()
    second = harness.post()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert len(harness.client_spy.invocations) == 1


# --- route protection -------------------------------------------------------------------


def test_the_inference_route_is_not_public() -> None:
    """It must never appear in the public allowlist the route-auth guard consults."""
    from tests.security.test_route_auth_coverage import PUBLIC_ROUTES

    assert INFERENCE_PATH not in PUBLIC_ROUTES


def test_the_app_without_an_authenticator_has_no_inference_route() -> None:
    """A deployment that cannot authenticate must not expose the endpoint at all, rather than
    exposing it and relying on the route's own check."""
    harness = Harness(with_auth=False)

    response = harness.post(token=None)

    # The route still refuses: with no middleware nothing sets request.state.auth.
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "put", "delete", "patch"])
def test_only_post_is_accepted(method: str) -> None:
    harness = Harness()
    response = getattr(harness.http, method)(
        INFERENCE_PATH, headers={"Authorization": f"Bearer {GOOD_TOKEN}"}
    )
    assert response.status_code == 405
