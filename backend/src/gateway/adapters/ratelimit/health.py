"""Shared-state health check (Phase 5 M4, ADR-0021).

M4 gave the gateway a second infrastructure dependency, and ``/healthz`` listed one. An operator
reading the surface built for exactly that question would have been told "database: ok" and nothing
else, while the deployment quietly enforced per-replica limits instead of the shared one. A health
endpoint that cannot report a dependency's failure is the "reports success while structurally
unable to fail" pattern this project treats as its recurring defect, so the dependency M4 added
reports here.

## It reports DEGRADED, and that is the whole point

``HealthState.DEGRADED`` existed from the moment the ops endpoints were built and had **never been
produced** - ``CheckResult`` carried a boolean, so the registry could only say OK or DOWN. Redis is
its first producer, and the state is not decoration:

* ``DOWN`` would be wrong and actively harmful. ``/readyz`` would answer 503, an orchestrator would
  pull the replica out of rotation, and ADR-0021's deliberate *degradation* would become the
  outage that ADR chose degraded-closed to avoid. The gateway is still serving, still limiting,
  still charging correctly.
* ``OK`` would be wrong the other way: the shared limit is not being enforced, N replicas are each
  admitting the configured rate, and the operator cannot see it from the surface they check first.

``HealthReport.is_ready`` is ``status is not DOWN``, so a degraded gateway stays ready. The state
shows up in ``/healthz`` and in the ``status`` field, which is where it belongs.

## Why it reads the limiter rather than pinging Redis

A ping answers "was Redis reachable just now, from this extra round-trip". This reports what the
**request path actually experienced** - the flag ``DegradedRateLimiter`` sets when a real
``acquire`` failed and the local bucket answered instead. Those come apart in the case that
matters: a Redis that accepts connections but fails or times out on ``EVAL`` would pass a ping and
still be failing every limiter call. It also costs nothing, which a health endpoint polled every
few seconds should.
"""

from __future__ import annotations

from gateway.adapters.ratelimit.degraded import DegradedRateLimiter
from gateway.application.ports.health import CheckResult


class SharedStateHealthCheck:
    """Reports whether ingress rate limiting is still being enforced *across* replicas."""

    def __init__(self, limiter: DegradedRateLimiter) -> None:
        self._limiter = limiter

    async def __call__(self) -> CheckResult:
        if self._limiter.degraded:
            return CheckResult.degraded(
                "rate-limit store unreachable; limits are enforced per replica, not shared"
            )
        return CheckResult.ok("shared")
