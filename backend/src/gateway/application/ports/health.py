"""Health-check primitives (framework-free).

Kept in the application layer so both the delivery ops-router and adapter health
checks (DB, Redis, providers) can share them without violating the dependency rule.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class HealthState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of a single dependency check."""

    healthy: bool
    detail: str | None = None


CheckFn = Callable[[], Awaitable[CheckResult]]


class HealthCheck(Protocol):
    """A named dependency check; adapters implement this."""

    async def __call__(self) -> CheckResult: ...
