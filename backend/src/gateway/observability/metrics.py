"""Cross-cutting Prometheus metrics (exported by the ops ``/metrics`` endpoint).

Counters are module-level singletons on the default registry so any layer can record without
threading a registry through constructors. **Label values must be low-cardinality and never
sensitive** — reasons are drawn from a fixed vocabulary, never from exception text, user input,
tokens, or secrets (NFR-SEC03).
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

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
