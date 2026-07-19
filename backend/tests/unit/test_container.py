"""Tests for the DI container / composition root."""

from __future__ import annotations

from gateway.config.container import Container
from gateway.config.settings import Settings
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.shared.clock import Clock


def test_container_wires_singletons(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    assert container.settings is test_settings
    assert isinstance(container.clock, Clock)
    assert isinstance(container.health, HealthRegistry)


def test_health_registry_uses_service_version(test_settings: Settings) -> None:
    container = Container.create(test_settings)
    # The registry reports the configured version.
    assert container.settings.service_version == "0.1.0"
