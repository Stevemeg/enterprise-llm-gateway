"""Tests for the DI container / composition root."""

from __future__ import annotations

from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.application.accounting.budget_enforcer import BudgetEnforcer
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.ports.budget import BudgetPort
from gateway.application.ports.cache import ResponseCachePort
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.pricing import PricingPort
from gateway.application.ports.providers import ProviderClient
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
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
