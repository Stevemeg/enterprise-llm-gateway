"""Tests for the DI container / composition root."""

from __future__ import annotations

from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.application.accounting.budget_enforcer import BudgetEnforcer
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.ports.budget import BudgetPort
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.pricing import PricingPort
from gateway.application.ports.providers import ProviderClient
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.config.container import Container
from gateway.config.settings import Settings
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.shared.clock import Clock


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


def test_health_registry_uses_service_version(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    # The registry reports the configured version.
    assert container.settings.service_version == "0.1.0"
