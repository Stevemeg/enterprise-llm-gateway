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
        return CheckResult.ok("connected")

    async def unhealthy() -> CheckResult:
        return CheckResult.down("timeout")

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
        return CheckResult.ok()

    registry.register("x", check)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("x", check)


# --- Phase 5 M4: the third state, which was declared and unproducible until ADR-0021 ------------


async def test_a_degraded_dependency_keeps_the_process_ready() -> None:
    """The distinction the whole change exists for. A degraded rate-limit store means the gateway
    is still serving on a weaker rule; answering /readyz with 503 would make an orchestrator pull
    the replica and turn ADR-0021's deliberate degradation into the outage it chose to avoid."""
    registry = HealthRegistry(version="1.0.0", clock=FixedClock())

    async def impaired() -> CheckResult:
        return CheckResult.degraded("store unreachable; limits are per replica")

    registry.register("shared_rate_limit_state", impaired)
    report = await registry.run()

    assert report.status is HealthState.DEGRADED
    assert report.is_ready is True, "a degraded dependency must not deregister the replica"
    assert report.components[0].detail == "store unreachable; limits are per replica"


async def test_degraded_is_visible_rather_than_reported_as_ok() -> None:
    """The other failure direction: hiding it would leave the operator reading "ok" while the
    shared limit is not being enforced anywhere."""
    registry = HealthRegistry(version="1.0.0", clock=FixedClock())

    async def fine() -> CheckResult:
        return CheckResult.ok()

    async def impaired() -> CheckResult:
        return CheckResult.degraded("impaired")

    registry.register("database", fine)
    registry.register("shared_rate_limit_state", impaired)
    report = await registry.run()

    assert report.status is HealthState.DEGRADED
    states = {c.name: c.state for c in report.components}
    assert states == {"database": HealthState.OK, "shared_rate_limit_state": HealthState.DEGRADED}


async def test_down_outranks_degraded_however_they_are_ordered() -> None:
    """Worst-wins, and not by accident of registration order or enum declaration order."""
    for order in (("degraded", "down"), ("down", "degraded")):
        registry = HealthRegistry(version="1.0.0", clock=FixedClock())
        for name in order:
            result = CheckResult.degraded("d") if name == "degraded" else CheckResult.down("x")

            async def check(captured: CheckResult = result) -> CheckResult:
                return captured

            registry.register(name, check)

        report = await registry.run()
        assert report.status is HealthState.DOWN, f"order {order} lost the DOWN"
        assert report.is_ready is False


def test_a_degradation_must_explain_itself() -> None:
    """``detail`` is required on ``degraded`` and optional elsewhere: a degradation nobody can act
    on is noise, and "degraded how" is the operator's first question."""
    assert CheckResult.degraded("because X").detail == "because X"
    assert CheckResult.ok().detail == "ok"
