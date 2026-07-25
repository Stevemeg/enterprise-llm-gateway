"""In-process circuit breaker (ADR-0016 Slice 20, ADR-0012 / FR-037-038) - the Rule-4 first
implementation of ``CircuitBreaker``.

Classic three-state breaker, per ``(organization_id, provider)``:

* **CLOSED** - healthy. Consecutive *transient provider faults* are counted; reaching
  ``failure_threshold`` trips the circuit **OPEN** and records the moment.
* **OPEN** - excluded from routing. After ``cooldown`` has elapsed, the next ``assess`` moves it
  to **HALF_OPEN** so exactly one request may probe recovery.
* **HALF_OPEN** - one probe is in flight. A success closes the circuit and clears the count; a
  transient fault re-opens it and restarts the cooldown.

A success in any state clears the failure count (a provider that just served is not accumulating
toward a trip). A non-transient outcome (client error, unclassified failure) is ignored entirely -
it says nothing about *this* provider's health and must not be able to trip a healthy breaker with
a caller's bad requests.

## Tenant isolation without RLS

State is keyed by ``(organization_id, provider)``, so one tenant's failures never open another
tenant's circuit for the same provider - the same isolation RLS gives storage, here enforced by
the key rather than by the database, because this state never touches the database. A provider is a
*shared* resource, but its health is observed per tenant: tenant A hammering a provider into
rate-limiting should not blind tenant B, whose traffic to it may be fine.

## Time and determinism

Transitions are driven by an injected ``Clock`` (wall-clock ``now``), never ``time.time()``
directly, so a test can advance time deterministically. ``assess`` is the only place the
time-driven ``OPEN -> HALF_OPEN`` transition happens, because that is exactly the read that must
decide "may a probe go through now".

Not thread-safe by design: the gateway serves each request on one asyncio task and this state is
mutated only from within a single event loop, so there is no preemption to guard against. A
multi-process deployment does not share this state at all - that is the durable ``provider_health``
snapshot work deferred until ADR-0005 (see the port docstring).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from gateway.application.ports.circuit_breaker import (
    CircuitState,
    ProviderCallResult,
    ProviderCircuit,
)
from gateway.application.ports.providers import TRANSIENT_PROVIDER_ERROR_CATEGORIES
from gateway.observability.metrics import record_circuit_transition
from gateway.shared.clock import Clock

_DEFAULT_FAILURE_THRESHOLD = 5
_DEFAULT_COOLDOWN = timedelta(seconds=30)

#: Transition -> metric label. Kept beside the transitions so a new state edge cannot be recorded
#: with an unbounded label value.
_OPENED = "opened"
_CLOSED = "closed"
_HALF_OPENED = "half_opened"


@dataclass
class _Circuit:
    """Mutable per-(org, provider) state. Not a domain object - the runtime's scratch, like
    ``AgentContext``; the immutable view callers see is ``ProviderCircuit``."""

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: datetime | None = None


@dataclass
class CircuitBreakerConfig:
    """How many transient faults trip a circuit, and how long it stays open.

    A typed object rather than two loose numbers (Rule 3): both are limits a future caller may want
    to tune per tenant or per provider, and an untyped pair would let a caller swap them silently -
    the same reasoning ``RetryPolicy`` uses. Conservative defaults; validated on construction so a
    misconfiguration fails loudly at startup, not as a breaker that never trips or trips at once.
    """

    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD
    cooldown: timedelta = _DEFAULT_COOLDOWN

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError(f"failure_threshold must be >= 1, got {self.failure_threshold}")
        if self.cooldown < timedelta(0):
            raise ValueError(f"cooldown must not be negative, got {self.cooldown}")


class InMemoryCircuitBreaker:
    """Per-tenant, per-provider circuit breaker held in process memory."""

    def __init__(self, clock: Clock, config: CircuitBreakerConfig | None = None) -> None:
        self._clock = clock
        self._config = config or CircuitBreakerConfig()
        self._circuits: dict[tuple[UUID, str], _Circuit] = {}

    def observe(self, *, organization_id: UUID, provider: str, result: ProviderCallResult) -> None:
        if result.ok:
            self._on_success(organization_id, provider)
        elif result.error_category in TRANSIENT_PROVIDER_ERROR_CATEGORIES:
            self._on_transient_failure(organization_id, provider)
        # Any other outcome (client error, unclassified) is deliberately ignored: it is not
        # evidence about this provider's health (see the module docstring).

    def _on_success(self, organization_id: UUID, provider: str) -> None:
        circuit = self._circuits.get((organization_id, provider))
        if circuit is None:
            return  # never failed, still CLOSED - nothing to record
        was_recovering = circuit.state is CircuitState.HALF_OPEN
        circuit.consecutive_failures = 0
        circuit.opened_at = None
        if circuit.state is not CircuitState.CLOSED:
            circuit.state = CircuitState.CLOSED
            if was_recovering:
                record_circuit_transition(provider=provider, transition=_CLOSED)

    def _on_transient_failure(self, organization_id: UUID, provider: str) -> None:
        key = (organization_id, provider)
        circuit = self._circuits.setdefault(key, _Circuit())
        if circuit.state is CircuitState.HALF_OPEN:
            # The probe failed: straight back to OPEN, cooldown restarts from now.
            self._trip(circuit, provider)
            return
        circuit.consecutive_failures += 1
        if (
            circuit.state is CircuitState.CLOSED
            and circuit.consecutive_failures >= self._config.failure_threshold
        ):
            self._trip(circuit, provider)

    def _trip(self, circuit: _Circuit, provider: str) -> None:
        circuit.state = CircuitState.OPEN
        circuit.opened_at = self._clock.now()
        record_circuit_transition(provider=provider, transition=_OPENED)

    def assess(
        self, *, organization_id: UUID, providers: Sequence[str]
    ) -> tuple[ProviderCircuit, ...]:
        now = self._clock.now()
        assessments: list[ProviderCircuit] = []
        for provider in providers:
            circuit = self._circuits.get((organization_id, provider))
            if circuit is None:
                assessments.append(ProviderCircuit(provider=provider, state=CircuitState.CLOSED))
                continue
            if (
                circuit.state is CircuitState.OPEN
                and circuit.opened_at is not None
                and now - circuit.opened_at >= self._config.cooldown
            ):
                circuit.state = CircuitState.HALF_OPEN
                record_circuit_transition(provider=provider, transition=_HALF_OPENED)
            assessments.append(ProviderCircuit(provider=provider, state=circuit.state))
        return tuple(assessments)
