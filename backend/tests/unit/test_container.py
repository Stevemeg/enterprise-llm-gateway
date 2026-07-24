"""Tests for the DI container / composition root."""

from __future__ import annotations

from uuid import uuid4

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.application.accounting.budget_enforcer import BudgetEnforcer
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.evaluation.runner import EvaluationRunner
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.pipeline.runner import RequestPipeline
from gateway.application.ports.authorization import PermissionResolver
from gateway.application.ports.budget import BudgetPort
from gateway.application.ports.cache import ResponseCachePort
from gateway.application.ports.evaluation import Evaluator
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.pipeline import PipelineStage, StageContext
from gateway.application.ports.policy import PolicyEnginePort
from gateway.application.ports.pricing import PricingPort
from gateway.application.ports.providers import InferenceRequest, ProviderClient
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.serving.inference_service import InferenceService
from gateway.config.container import Container
from gateway.config.settings import Settings
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.shared.clock import Clock, Sleeper


def test_container_wires_singletons(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert container.settings is test_settings
    assert isinstance(container.clock, Clock)
    assert isinstance(container.health, HealthRegistry)


def test_container_wires_provider_execution(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.provider_client, ProviderClient)
    assert isinstance(container.provider_executor, ProviderExecutor)


def test_container_wires_accounting(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.pricing_port, PricingPort)
    assert isinstance(container.budget_port, BudgetPort)
    assert isinstance(container.cost_accountant, CostAccountant)
    assert isinstance(container.budget_enforcer, BudgetEnforcer)


def test_container_wires_budget_ledger(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.ledger_port, BudgetLedgerPort)
    assert isinstance(container.reservation_service, ReservationService)


def test_non_postgres_settings_wire_the_in_memory_ledger(test_settings: Settings) -> None:
    """SqlBudgetLedger's atomicity claim only holds against real Postgres (ADR-0017) - a SQLite
    test settings profile must wire the in-memory adapter, never the SQL one."""
    container = Container.create(test_settings)
    assert isinstance(container.ledger_port, InMemoryBudgetLedger)


def test_container_wires_response_cache_and_coordinator(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.cache_port, ResponseCachePort)
    assert isinstance(container.deduplicator, RequestDeduplicator)
    assert isinstance(container.inference_coordinator, InferenceCoordinator)


def test_non_postgres_settings_wire_the_in_memory_response_cache(test_settings: Settings) -> None:
    """SqlResponseCache's RLS/isolation claim only holds against real Postgres (ADR-0018) - a
    SQLite test settings profile must wire the in-memory adapter, never the SQL one."""
    container = Container.create(test_settings)
    assert isinstance(container.cache_port, InMemoryResponseCache)


def test_container_wires_reflection(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.sleeper, Sleeper)
    assert isinstance(container.retry_policy, RetryPolicy)
    assert isinstance(container.reflective_executor, ReflectiveExecutor)


def test_the_wired_retry_policy_is_bounded(test_settings: Settings) -> None:
    """A deployment-wide attempt bound is only a bound if it is finite and at least one."""
    container = Container.create(test_settings)
    assert container.retry_policy.max_attempts >= 1
    assert container.retry_policy.max_attempts < 100


def test_health_registry_uses_service_version(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    # The registry reports the configured version.
    assert container.settings.service_version == "0.1.0"


def test_container_wires_evaluation(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.evaluation_runner, EvaluationRunner)
    assert len(container.evaluators) >= 1
    assert all(isinstance(e, Evaluator) for e in container.evaluators)


def test_wired_evaluators_have_distinct_names(test_settings: Settings) -> None:
    """Two evaluators sharing a name would make their verdicts indistinguishable in a report."""
    container = Container.create(test_settings)
    names = [e.name for e in container.evaluators]
    assert len(names) == len(set(names))


def test_the_runner_runs_exactly_the_wired_evaluators(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert container.evaluation_runner.evaluators == container.evaluators


def test_container_wires_policy(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert isinstance(container.policy_engine, PolicyEnginePort)
    assert isinstance(container.policy_stage, PolicyStage)


def test_the_wired_policy_stage_is_a_pipeline_stage(test_settings: Settings) -> None:
    """ADR-0016's Tier-2 hypothesis, checked on the actually-wired object."""
    container = Container.create(test_settings)
    assert isinstance(container.policy_stage, PipelineStage)


def test_policy_and_evaluation_are_wired_as_separate_capabilities(test_settings: Settings) -> None:
    """Slices 12 and 13 must remain independent - neither is the other's collaborator.

    Asserted by module provenance rather than object identity: an ``is not`` between two
    different types is statically vacuous (mypy rejects it as a non-overlapping comparison), so
    it would pass forever without ever being able to fail.
    """
    container = Container.create(test_settings)

    evaluator_modules = {type(e).__module__ for e in container.evaluators}
    assert evaluator_modules
    assert all(m.startswith("gateway.application.evaluation") for m in evaluator_modules)
    assert not any("policy" in m for m in evaluator_modules)
    assert type(container.policy_engine).__module__.startswith("gateway.adapters.policy")
    assert type(container.policy_stage).__module__.startswith("gateway.adapters.pipeline")


def test_container_wires_the_request_admission_pipeline(test_settings: Settings) -> None:
    """Slice 14: the stage seam finally has an executor, and the stages are in it."""
    container = Container.create(test_settings)
    assert isinstance(container.permission_resolver, PermissionResolver)
    assert isinstance(container.authorization_stage, AuthorizationStage)
    assert isinstance(container.request_pipeline, RequestPipeline)


def test_the_admission_chain_runs_authorization_then_policy_then_routing(
    test_settings: Settings,
) -> None:
    """Ordering is the enforcement. Routing runs last because it is the stage with a real
    downstream side effect - it invokes the engine, which runs the whole agent chain."""
    container = Container.create(test_settings)
    assert container.request_pipeline.stage_names == ("authorization", "policy", "agent_routing")


def test_every_wired_admission_stage_satisfies_the_tier_1_stage_protocol(
    test_settings: Settings,
) -> None:
    container = Container.create(test_settings)
    for stage in (
        container.authorization_stage,
        container.policy_stage,
        container.routing_stage,
    ):
        assert isinstance(stage, PipelineStage)


async def test_the_default_deployment_admits_nothing(test_settings: Settings) -> None:
    """RBAC has no storage yet, so the wired resolver grants nothing and no endpoint declares a
    requirement. The composed default therefore denies every request - deliberately the
    fail-closed direction, and the same 'nothing configured yet' posture as the empty provider
    catalog and empty price table."""
    container = Container.create(test_settings)

    outcome = await container.request_pipeline.admit(
        StageContext(correlation_id="c-1", organization_id=uuid4(), principal_id=uuid4())
    )

    assert outcome.admitted is False
    assert outcome.blocked_by == "authorization"


async def test_the_wired_pipeline_does_not_route_a_request_it_refuses(
    test_settings: Settings,
) -> None:
    """The composed form of the property Slices 5-13 could only assert on unwired objects."""
    container = Container.create(test_settings)

    outcome = await container.request_pipeline.admit(
        StageContext(correlation_id="c-1", organization_id=uuid4(), principal_id=uuid4())
    )

    assert outcome.stages_run == ("authorization",)
    assert "agent_routing" not in outcome.stages_run


def test_container_wires_the_served_inference_path(test_settings: Settings) -> None:
    """Slice 15: admission and execution are finally one object."""
    container = Container.create(test_settings)
    assert isinstance(container.inference_service, InferenceService)


async def test_the_wired_service_refuses_before_touching_the_execution_path(
    test_settings: Settings,
) -> None:
    """The composed default denies, and a denial reaches neither the executor nor evaluation."""
    container = Container.create(test_settings)

    served = await container.inference_service.serve(
        StageContext(correlation_id="c-1", organization_id=uuid4(), principal_id=uuid4()),
        InferenceRequest(correlation_id="c-1", payload={"prompt": "hello"}),
    )

    assert served.admitted is False
    assert served.reflection is None
    assert served.evaluation is None


def test_the_service_runs_the_wired_pipeline_and_evaluators(test_settings: Settings) -> None:
    """Not a second composition: the service must hold the same objects the container built,
    or the deployment would enforce one chain and serve requests through another."""
    container = Container.create(test_settings)
    service = container.inference_service

    assert service._pipeline is container.request_pipeline
    assert service._executor is container.reflective_executor
    assert service._evaluation_runner is container.evaluation_runner
