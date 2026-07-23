"""LocalPolicyEngine - deterministic, in-process policy evaluation (ADR-0016 Slice 13).

Enforces one policy: **a request payload may not exceed a configured serialized size.** That is a
deliberately small first policy, chosen because it is the only one this repository can express
today without inventing data:

* It reads the inbound payload, which already flows through ``StageContext.attributes["request"]``
  (a convention ``AgentRoutingStage`` established in Slice 6).
* It needs no data-classification system, no per-organization policy store and no model-capability
  catalog - none of which exist. Inventing any of them to justify a richer first policy would be
  precisely the speculative infrastructure Rule 5/GP-1 forbid.
* It is genuinely useful rather than a demonstration: an oversized payload is bounded *before* the
  budget reservation and the provider call, so it costs nothing to reject. Slice 9's estimator
  already derives its reservation from payload length, which means an unbounded payload is
  simultaneously a cost problem and an abuse vector.

## Why OPA is NOT here

ADR-0016 names OPA as the eventual policy mechanism. It is deliberately **deferred**, on the same
evidence-first reasoning ADR-0017 applied to Redis Lua and ADR-0018 to the pgvector semantic tier:
there is no OPA server, no Rego bundle, no bundle-distribution mechanism, no deployment
configuration for one, and no consumer that needs policy authored outside this process. An OPA
*adapter* built now would be a fake integration - an interface shaped like a remote engine with
nothing on the other end - and its parity tests would compare a stub against itself. When a real
policy-distribution consumer exists, it implements ``PolicyEnginePort`` beside this class and the
stage does not change: that substitutability is the entire point of the port, and is what makes
deferring OPA a decision rather than an omission.

Size is measured over a canonical JSON encoding (sorted keys, no incidental whitespace) so the
same payload always measures the same regardless of how its dict was built - the same determinism
requirement ``compute_cache_key`` has, for the same reason.
"""

from __future__ import annotations

import json

from gateway.application.ports.policy import (
    PolicyEffect,
    PolicyQuery,
    PolicyVerdict,
)

#: Caller-visible denial text. Deliberately generic: it names no threshold and no rule, because
#: telling a caller exactly which control stopped them and where its limit sits is a
#: reconnaissance aid (the same reasoning ``AuthorizationStage`` applies to permission names).
_DENIAL_REASON = "request rejected by policy"

_MAX_REQUEST_BYTES = 128 * 1024


class LocalPolicyEngine:
    """Evaluates deployment policy locally, with no external dependency."""

    def __init__(self, *, max_request_bytes: int = _MAX_REQUEST_BYTES) -> None:
        if max_request_bytes < 1:
            raise ValueError(
                f"max_request_bytes must be at least 1, got {max_request_bytes} - a limit of zero "
                "would deny every request including empty ones, which is a misconfiguration "
                "rather than a policy"
            )
        self._max_request_bytes = max_request_bytes

    @property
    def max_request_bytes(self) -> int:
        return self._max_request_bytes

    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        try:
            encoded = json.dumps(
                dict(query.payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            # A payload that cannot be canonically encoded cannot be measured, and a limit that
            # cannot be measured has not been satisfied. Fail closed rather than waving it
            # through - the alternative is an unbounded payload bypassing the control by being
            # malformed enough to defeat the check.
            return PolicyVerdict(
                effect=PolicyEffect.DENY,
                reason=_DENIAL_REASON,
                rule="max_request_bytes",
                detail={
                    "organization_id": str(query.organization_id),
                    "unmeasurable_payload": True,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

        size = len(encoded)
        if size > self._max_request_bytes:
            return PolicyVerdict(
                effect=PolicyEffect.DENY,
                reason=_DENIAL_REASON,
                rule="max_request_bytes",
                detail={
                    "organization_id": str(query.organization_id),
                    "request_bytes": size,
                    "limit_bytes": self._max_request_bytes,
                },
            )
        return PolicyVerdict(
            effect=PolicyEffect.ALLOW,
            rule="max_request_bytes",
            detail={"request_bytes": size, "limit_bytes": self._max_request_bytes},
        )
