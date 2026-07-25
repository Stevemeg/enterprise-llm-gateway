"""In-memory circuit breaker (ADR-0016 Slice 20, ADR-0012 / FR-037-038).

The property under test is the circuit-breaker state machine and the two invariants that keep it
from misfiring: only a **transient provider fault** trips it (a caller's bad request must not), and
one tenant's failures must never open another tenant's circuit for the same provider.

Failure-first: the ways a breaker could wrongly EXCLUDE a healthy provider, or wrongly ADMIT a
failing one, are asserted before the recovery path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from gateway.adapters.health.in_memory_circuit_breaker import (
    CircuitBreakerConfig,
    InMemoryCircuitBreaker,
)
from gateway.application.ports.circuit_breaker import (
    CircuitState,
    ProviderCallResult,
)
from gateway.application.ports.providers import ProviderErrorCategory

ORG = uuid4()
OTHER_ORG = uuid4()
PROVIDER = "openai"


class SteppingClock:
    """Advances only when told, so cooldown transitions are deterministic."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


def _fault(
    category: ProviderErrorCategory = ProviderErrorCategory.SERVER_ERROR,
) -> ProviderCallResult:
    return ProviderCallResult(ok=False, error_category=category)


_SUCCESS = ProviderCallResult(ok=True)


def _state(
    breaker: InMemoryCircuitBreaker, org: UUID = ORG, provider: str = PROVIDER
) -> CircuitState:
    (assessment,) = breaker.assess(organization_id=org, providers=(provider,))
    return assessment.state


def _breaker(
    clock: SteppingClock, *, threshold: int = 3, cooldown: float = 30.0
) -> InMemoryCircuitBreaker:
    return InMemoryCircuitBreaker(
        clock,
        CircuitBreakerConfig(failure_threshold=threshold, cooldown=timedelta(seconds=cooldown)),
    )


# ------------------------------------------------------------------ config validation


@pytest.mark.parametrize("threshold", [0, -1])
def test_a_threshold_below_one_is_rejected(threshold: int) -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreakerConfig(failure_threshold=threshold)


def test_a_negative_cooldown_is_rejected() -> None:
    with pytest.raises(ValueError, match="cooldown"):
        CircuitBreakerConfig(cooldown=timedelta(seconds=-1))


# ------------------------------------------------------------------ must not wrongly exclude


def test_an_unseen_provider_is_closed() -> None:
    """Absence of evidence is not evidence of failure - a brand-new provider must be usable."""
    breaker = _breaker(SteppingClock())
    assert _state(breaker) is CircuitState.CLOSED


def test_failures_below_the_threshold_do_not_open_the_circuit() -> None:
    breaker = _breaker(SteppingClock(), threshold=3)
    for _ in range(2):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker) is CircuitState.CLOSED


@pytest.mark.parametrize(
    "category",
    [ProviderErrorCategory.INVALID_REQUEST, ProviderErrorCategory.AUTHENTICATION],
)
def test_client_side_failures_never_trip_the_circuit(category: ProviderErrorCategory) -> None:
    """A malformed or misauthenticated request is the caller's fault and would recur against any
    provider. Counting it would let bad requests trip a healthy provider's breaker."""
    breaker = _breaker(SteppingClock(), threshold=3)
    for _ in range(10):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault(category))
    assert _state(breaker) is CircuitState.CLOSED


def test_an_unclassified_failure_never_trips_the_circuit() -> None:
    breaker = _breaker(SteppingClock(), threshold=3)
    for _ in range(10):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=ProviderCallResult(ok=False))
    assert _state(breaker) is CircuitState.CLOSED


def test_a_success_resets_the_failure_count() -> None:
    """Two faults, a success, two faults must NOT open a threshold-3 circuit: the success cleared
    the run, so the count never reaches three consecutively."""
    breaker = _breaker(SteppingClock(), threshold=3)
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_SUCCESS)
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker) is CircuitState.CLOSED


# ------------------------------------------------------------------ tenant isolation


def test_one_tenants_failures_do_not_open_another_tenants_circuit() -> None:
    breaker = _breaker(SteppingClock(), threshold=3)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker, org=ORG) is CircuitState.OPEN
    assert _state(breaker, org=OTHER_ORG) is CircuitState.CLOSED


# ------------------------------------------------------------------ opening and recovery


def test_reaching_the_threshold_opens_the_circuit() -> None:
    breaker = _breaker(SteppingClock(), threshold=3)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker) is CircuitState.OPEN


def test_an_open_circuit_stays_open_until_the_cooldown_elapses() -> None:
    clock = SteppingClock()
    breaker = _breaker(clock, threshold=3, cooldown=30.0)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    clock.advance(29)
    assert _state(breaker) is CircuitState.OPEN


def test_after_the_cooldown_the_circuit_half_opens_to_allow_a_probe() -> None:
    clock = SteppingClock()
    breaker = _breaker(clock, threshold=3, cooldown=30.0)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    clock.advance(30)
    assert _state(breaker) is CircuitState.HALF_OPEN


def test_a_successful_probe_closes_the_circuit() -> None:
    clock = SteppingClock()
    breaker = _breaker(clock, threshold=3, cooldown=30.0)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    clock.advance(30)
    assert _state(breaker) is CircuitState.HALF_OPEN  # drives OPEN -> HALF_OPEN
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_SUCCESS)
    assert _state(breaker) is CircuitState.CLOSED


def test_a_failed_probe_reopens_the_circuit_and_restarts_the_cooldown() -> None:
    clock = SteppingClock()
    breaker = _breaker(clock, threshold=3, cooldown=30.0)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    clock.advance(30)
    assert _state(breaker) is CircuitState.HALF_OPEN
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker) is CircuitState.OPEN
    clock.advance(29)
    assert _state(breaker) is CircuitState.OPEN, "the cooldown must restart from the failed probe"
    clock.advance(1)
    assert _state(breaker) is CircuitState.HALF_OPEN


def test_a_recovered_circuit_can_open_again_on_a_fresh_run_of_failures() -> None:
    """A closed-after-recovery circuit must not carry stale failures: it takes a full fresh run to
    re-open, proving the count was cleared on close."""
    clock = SteppingClock()
    breaker = _breaker(clock, threshold=3, cooldown=30.0)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    clock.advance(30)
    _state(breaker)  # -> HALF_OPEN
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_SUCCESS)  # -> CLOSED
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker) is CircuitState.CLOSED, "two faults after recovery must not re-open"
    breaker.observe(organization_id=ORG, provider=PROVIDER, result=_fault())
    assert _state(breaker) is CircuitState.OPEN


# ------------------------------------------------------------------ multi-provider assessment


def test_assess_reports_each_provider_independently() -> None:
    clock = SteppingClock()
    breaker = _breaker(clock, threshold=3)
    for _ in range(3):
        breaker.observe(organization_id=ORG, provider="down", result=_fault())
    assessments = {
        a.provider: a.state for a in breaker.assess(organization_id=ORG, providers=("up", "down"))
    }
    assert assessments["up"] is CircuitState.CLOSED
    assert assessments["down"] is CircuitState.OPEN
