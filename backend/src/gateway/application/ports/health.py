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
    """Outcome of a single dependency check.

    ## Phase 5 M4: carries a ``HealthState``, not a boolean

    This was ``healthy: bool``, which made ``HealthState.DEGRADED`` **unproducible** - declared in
    the enum above since the ops endpoints were built, and never returned by anything. The
    registry could only map ``False`` to ``DOWN``.

    Redis is the active consumer that forced the change (Rule 5), and it could not be implemented
    correctly without it. ADR-0021 decided that a rate-limit store outage **degrades** the gateway
    rather than stopping it: the local bucket still enforces the same policy. Reporting that as
    ``DOWN`` would make ``/readyz`` answer 503, an orchestrator would pull the replica out of
    rotation, and a deliberate degradation would become the outage ADR-0021 exists to avoid.
    Reporting it as ``OK`` would hide a dependency failure from the surface operators read first.
    Neither is true, and with a boolean neither could be avoided.

    Two booleans (``healthy`` + ``degraded``) were rejected: three states encoded as two flags
    admits ``healthy=False, degraded=True``, which means nothing, and Rule 3 exists for exactly
    this - represent the concept, do not spell it with conventions.
    """

    state: HealthState
    detail: str | None = None

    @classmethod
    def ok(cls, detail: str | None = "ok") -> CheckResult:
        return cls(state=HealthState.OK, detail=detail)

    @classmethod
    def degraded(cls, detail: str) -> CheckResult:
        """Reachable but impaired. **Still ready**: the process can serve.

        A detail is required rather than optional - a degradation nobody can act on is noise, and
        the operator's first question is always "degraded how".
        """
        return cls(state=HealthState.DEGRADED, detail=detail)

    @classmethod
    def down(cls, detail: str) -> CheckResult:
        return cls(state=HealthState.DOWN, detail=detail)


CheckFn = Callable[[], Awaitable[CheckResult]]


class HealthCheck(Protocol):
    """A named dependency check; adapters implement this."""

    async def __call__(self) -> CheckResult: ...
