"""Health registry + report shaping for the ops endpoints (NFR-O03).

Primitives (``HealthState``, ``CheckResult``, ``CheckFn``) live in the application layer
so adapters can produce checks without depending on delivery (ADR-0001). This module
owns aggregation: readiness/health is DOWN if any check fails; a raising check is DOWN.
"""

from __future__ import annotations

from dataclasses import dataclass

from gateway.application.ports.health import CheckFn, HealthState
from gateway.shared.clock import Clock


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    state: HealthState
    detail: str | None


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: HealthState
    version: str
    checked_at: str
    components: tuple[ComponentHealth, ...]

    @property
    def is_ready(self) -> bool:
        return self.status is not HealthState.DOWN


class HealthRegistry:
    """Registers and runs named health checks."""

    def __init__(self, *, version: str, clock: Clock) -> None:
        self._version = version
        self._clock = clock
        self._checks: dict[str, CheckFn] = {}

    def register(self, name: str, check: CheckFn) -> None:
        if name in self._checks:
            raise ValueError(f"Health check {name!r} is already registered")
        self._checks[name] = check

    async def run(self) -> HealthReport:
        components: list[ComponentHealth] = []
        overall = HealthState.OK
        for name, check in self._checks.items():
            try:
                result = await check()
            except Exception as exc:  # a check must never break health reporting
                components.append(ComponentHealth(name, HealthState.DOWN, f"check raised: {exc!s}"))
                overall = HealthState.DOWN
                continue
            state = HealthState.OK if result.healthy else HealthState.DOWN
            if state is HealthState.DOWN:
                overall = HealthState.DOWN
            components.append(ComponentHealth(name, state, result.detail))
        return HealthReport(
            status=overall,
            version=self._version,
            checked_at=self._clock.now().isoformat(),
            components=tuple(components),
        )
