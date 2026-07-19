"""Tests for the health-check registry."""

from __future__ import annotations

import pytest

from gateway.application.ports.health import CheckResult, HealthState
from gateway.delivery.http.ops.health import HealthRegistry
from tests.conftest import FixedClock


async def test_empty_registry_is_ok() -> None:
    registry = HealthRegistry(version="1.2.3", clock=FixedClock())
    report = await registry.run()
    assert report.status is HealthState.OK
    assert report.is_ready
    assert report.version == "1.2.3"
    assert report.components == ()


async def test_failing_check_marks_report_down() -> None:
    registry = HealthRegistry(version="1.0.0", clock=FixedClock())

    async def healthy() -> CheckResult:
        return CheckResult(healthy=True, detail="connected")

    async def unhealthy() -> CheckResult:
        return CheckResult(healthy=False, detail="timeout")

    registry.register("postgres", healthy)
    registry.register("redis", unhealthy)

    report = await registry.run()
    assert report.status is HealthState.DOWN
    assert not report.is_ready
    states = {component.name: component.state for component in report.components}
    assert states["postgres"] is HealthState.OK
    assert states["redis"] is HealthState.DOWN


async def test_raising_check_is_treated_as_down() -> None:
    registry = HealthRegistry(version="1.0.0", clock=FixedClock())

    async def broken() -> CheckResult:
        raise RuntimeError("boom")

    registry.register("provider", broken)
    report = await registry.run()
    assert report.status is HealthState.DOWN
    assert report.components[0].detail is not None
    assert "boom" in report.components[0].detail


def test_duplicate_registration_is_rejected() -> None:
    registry = HealthRegistry(version="1.0.0", clock=FixedClock())

    async def check() -> CheckResult:
        return CheckResult(healthy=True)

    registry.register("x", check)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("x", check)
