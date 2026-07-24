"""Cross-cutting Prometheus metrics (exported by the ops ``/metrics`` endpoint).

Counters are module-level singletons on the default registry so any layer can record without
threading a registry through constructors. **Label values must be low-cardinality and never
sensitive** — reasons are drawn from a fixed vocabulary, never from exception text, user input,
tokens, or secrets (NFR-SEC03).

## Slice 16: the request path became observable, without a new seam

Slices 5-15 built an entire request path that recorded **nothing**: only the three auth-era
metrics below existed, so ``/metrics`` was live and blind to routing, execution, cost, budget,
caching, retry, evaluation and admission. This module now covers that path.

**No new architectural boundary was introduced, so no ADR was written.** The mechanism
(module-level singletons on the default registry), the exposition route, the cross-cutting layer
and its import contract, and the cardinality policy stated above all already existed. This slice
extends an established mechanism to new call sites and makes its already-documented policy
*structurally enforced* rather than merely written down. Under ADR-0016 that is a **Capability**
milestone: it creates no extension point, and Rule 1's admission test fails - observability's
absence would not have forced any interface to change when it was added, which is exactly what
adding it with zero interface changes demonstrates.

## Recording goes through the functions below, never through ``.labels()`` directly

Every ``record_*`` function owns three things its call sites must not re-implement:

1. **The label vocabulary.** Values are validated against a frozen allowlist and an unrecognised
   value becomes ``"unknown"`` rather than a new time series. Cardinality is therefore bounded at
   **runtime**, not merely by convention - a defect upstream cannot turn into an unbounded metric.
2. **Failure isolation.** Recording is best-effort: a metrics failure must never change a request's
   outcome (Slice 16 records facts and decides nothing). Exceptions are swallowed and logged at
   debug rather than propagated into the request path.
3. **The dependency direction.** These take ``str``, not application enums, so ``observability``
   stays a leaf that imports no application code. Call sites pass ``SomeClosedEnum.value``; the
   allowlists here mirror those enums and the cardinality guard checks the pairing.

Three labels are **configuration-bounded rather than enum-bounded** and are documented as such
instead of being claimed as closed: ``stage`` (the composition root's fixed stage chain),
``evaluator`` (the wired evaluator chain) and ``provider`` (the deployment's provider catalog).
None is request-supplied - a caller cannot introduce a new value for any of them - but their
bound comes from deployment configuration, not from a Python enum.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Final

from prometheus_client import Counter, Histogram

from gateway.observability.logging import get_logger

# Fixed, low-cardinality failure reasons. Never interpolate exception messages into labels.
REASON_TIMEOUT = "timeout"
REASON_TRANSPORT = "transport"
REASON_MALFORMED = "malformed"
REASON_UNKNOWN_KID = "unknown_kid"
REASON_RATE_LIMITED = "rate_limited"

oidc_jwks_fetch_failures = Counter(
    "gateway_oidc_jwks_fetch_failures_total",
    "IdP JWKS fetches that failed; the login fails closed when this happens.",
    labelnames=("reason",),
)

oidc_token_exchange_failures = Counter(
    "gateway_oidc_token_exchange_failures_total",
    "OIDC authorization-code exchanges that failed; the login fails closed.",
    labelnames=("reason",),
)


# Authentication latency. Labels are deliberately limited to (method, result) — both drawn from
# AuthenticationMethod / AuthenticationDecision, which are closed vocabularies. Never label with
# user ids, tenant ids, tokens, or exception text: that would explode cardinality and leak data.
auth_duration_seconds = Histogram(
    "gateway_auth_duration_seconds",
    "End-to-end authentication duration, by method and outcome.",
    labelnames=("method", "result"),
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


# --- Slice 16: request-path vocabulary -------------------------------------------------------

#: Substituted for any value outside its allowlist. An unexpected value must not be able to mint
#: a new time series - that is how a metric becomes an unbounded, and possibly sensitive, label.
UNKNOWN: Final = "unknown"

#: Labels whose bound is the deployment (composition root, evaluator chain, provider catalog)
#: rather than a Python enum. None is request-supplied - a caller cannot introduce a value for
#: any of them - but the distinction is recorded rather than claimed as closed.
CONFIGURATION_BOUNDED_LABELS: Final = frozenset({"stage", "evaluator", "provider"})

_LOGGER = get_logger("observability.metrics")

#: Latency buckets for one provider call. Wider than the auth histogram: an inference call is
#: expected in the hundreds-of-milliseconds-to-tens-of-seconds range, not single milliseconds.
_PROVIDER_BUCKETS: Final = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
#: End-to-end buckets. Includes the fast path (an admission denial returns in microseconds) and
#: the slow path (a retried inference).
_SERVED_BUCKETS: Final = (0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

# Value allowlists. Each mirrors a closed StrEnum in the application layer; the pairing is
# asserted by tests so a new enum member cannot silently start reporting as "unknown".
_STAGE_ACTIONS: Final = frozenset({"continue", "annotate", "block"})
_EXECUTION_OUTCOMES: Final = frozenset(
    {"cache_hit", "executed", "not_routed", "budget_denied", "budget_unavailable"}
)
#: Served outcomes are the execution outcomes plus the one terminal state that never reaches
#: execution at all. "not_admitted" is deliberately distinct: a refusal is not an execution
#: result, and collapsing them would make a denial indistinguishable from a provider failure.
NOT_ADMITTED: Final = "not_admitted"
_SERVED_OUTCOMES: Final = _EXECUTION_OUTCOMES | {NOT_ADMITTED}
_CACHE_RESULTS: Final = frozenset({"hit", "miss"})
#: "ok" plus every ProviderErrorCategory, plus the failure nobody classified. ``unclassified`` is
#: not the same as ``unknown``: the first is a real, expected state (``error_category is None``),
#: the second means a value fell outside this allowlist.
UNCLASSIFIED: Final = "unclassified"
_PROVIDER_OUTCOMES: Final = frozenset(
    {
        "ok",
        "timeout",
        "rate_limited",
        "server_error",
        "invalid_request",
        "authentication",
        UNCLASSIFIED,
    }
)
_RETRY_VERDICTS: Final = frozenset({"succeeded", "retry", "terminal_failure"})
_ROUTING_OUTCOMES: Final = frozenset(
    {"selected", "no_candidate", "blocked_by_policy", "budget_exceeded", "all_unhealthy"}
)
_EVALUATION_OUTCOMES: Final = frozenset({"passed", "failed", "error", "not_applicable"})
_RESERVATION_OUTCOMES: Final = frozenset({"reserved", "exceeded", "unavailable"})


admission_stage_decisions = Counter(
    "gateway_admission_stage_decisions_total",
    "Admission-chain verdicts by stage. action=block identifies which control refused.",
    labelnames=("stage", "action"),
)

served_requests = Counter(
    "gateway_served_requests_total",
    "Terminal outcome of one served inference request, including requests never admitted.",
    labelnames=("outcome",),
)

served_request_duration_seconds = Histogram(
    "gateway_served_request_duration_seconds",
    "End-to-end served-request duration, admission through evaluation.",
    labelnames=("outcome",),
    buckets=_SERVED_BUCKETS,
)

inference_attempts = Counter(
    "gateway_inference_attempts_total",
    "Coordinated execution attempts. Distinct from served requests: one retried request is "
    "several attempts.",
    labelnames=("outcome",),
)

cache_lookups = Counter(
    "gateway_cache_lookups_total",
    "Response-cache lookups by result; hit rate is derived from this.",
    labelnames=("result",),
)

provider_calls = Counter(
    "gateway_provider_calls_total",
    "Provider invocations by provider and outcome; the outcome is a category, never error text.",
    labelnames=("provider", "outcome"),
)

provider_call_duration_seconds = Histogram(
    "gateway_provider_call_duration_seconds",
    "Wall-clock duration of one provider invocation, measured by ProviderExecutor.",
    labelnames=("provider",),
    buckets=_PROVIDER_BUCKETS,
)

reflection_attempts = Counter(
    "gateway_reflection_attempts_total",
    "Retry-loop attempts by verdict; verdict=retry counts attempts that were retried.",
    labelnames=("verdict",),
)

routing_decisions = Counter(
    "gateway_routing_decisions_total",
    "Routing attempts by outcome; non-selected outcomes are explained refusals, not errors.",
    labelnames=("outcome",),
)

evaluations = Counter(
    "gateway_evaluations_total",
    "Evaluator verdicts. outcome=error is the evaluator failing, never the response failing.",
    labelnames=("evaluator", "outcome"),
)

budget_reservations = Counter(
    "gateway_budget_reservations_total",
    "Budget reservation attempts by outcome (reserved / exceeded / ledger unavailable).",
    labelnames=("outcome",),
)


def _bounded(value: str, allowed: Iterable[str]) -> str:
    """Constrain a label value to its allowlist, collapsing anything else to ``UNKNOWN``."""
    return value if value in allowed else UNKNOWN


def _record(operation: str, action: Callable[[], None]) -> None:
    """Run a metric mutation, never letting it reach the request path.

    Observability records facts; it must not be able to change one. A broken metric is a
    monitoring problem, and turning it into a failed inference would make the monitoring the
    outage.
    """
    try:
        action()
    except Exception as exc:  # pragma: no cover - exercised via a deliberately broken metric
        _LOGGER.debug("metric_record_failed", operation=operation, error=type(exc).__name__)


def record_admission_decision(*, stage: str, action: str) -> None:
    """One stage's verdict. ``stage`` is composition-root-bounded, ``action`` is StageAction."""
    _record(
        "admission_decision",
        lambda: admission_stage_decisions.labels(
            stage=stage, action=_bounded(action, _STAGE_ACTIONS)
        ).inc(),
    )


def record_served_request(*, outcome: str, duration_seconds: float) -> None:
    """The terminal outcome and elapsed time of one served request."""
    bounded = _bounded(outcome, _SERVED_OUTCOMES)
    _record("served_request", lambda: served_requests.labels(outcome=bounded).inc())
    _record(
        "served_request_duration",
        lambda: served_request_duration_seconds.labels(outcome=bounded).observe(duration_seconds),
    )


def record_inference_attempt(*, outcome: str) -> None:
    """One coordinated attempt (cache hit, execution, or a refusal before the provider)."""
    _record(
        "inference_attempt",
        lambda: inference_attempts.labels(outcome=_bounded(outcome, _EXECUTION_OUTCOMES)).inc(),
    )


def record_cache_lookup(*, hit: bool) -> None:
    _record(
        "cache_lookup",
        lambda: cache_lookups.labels(result="hit" if hit else "miss").inc(),
    )


def record_provider_call(*, provider: str, outcome: str, duration_seconds: float) -> None:
    """One provider invocation. ``provider`` comes from the catalog, never from the payload."""
    bounded = _bounded(outcome, _PROVIDER_OUTCOMES)
    _record(
        "provider_call",
        lambda: provider_calls.labels(provider=provider, outcome=bounded).inc(),
    )
    _record(
        "provider_call_duration",
        lambda: provider_call_duration_seconds.labels(provider=provider).observe(duration_seconds),
    )


def record_reflection_attempt(*, verdict: str) -> None:
    _record(
        "reflection_attempt",
        lambda: reflection_attempts.labels(verdict=_bounded(verdict, _RETRY_VERDICTS)).inc(),
    )


def record_routing_decision(*, outcome: str) -> None:
    _record(
        "routing_decision",
        lambda: routing_decisions.labels(outcome=_bounded(outcome, _ROUTING_OUTCOMES)).inc(),
    )


def record_evaluation(*, evaluator: str, outcome: str) -> None:
    """One evaluator's verdict. ``evaluator`` is bounded by the wired evaluator chain."""
    _record(
        "evaluation",
        lambda: evaluations.labels(
            evaluator=evaluator, outcome=_bounded(outcome, _EVALUATION_OUTCOMES)
        ).inc(),
    )


def record_budget_reservation(*, outcome: str) -> None:
    _record(
        "budget_reservation",
        lambda: budget_reservations.labels(outcome=_bounded(outcome, _RESERVATION_OUTCOMES)).inc(),
    )
