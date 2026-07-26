"""Deployment policy enforcement as a PipelineStage (ADR-0016 Slice 13).

**This is the test of ADR-0016's Tier-2 demotion of Policy Engine, and it passes.** The stage
implements ``PipelineStage`` with no change to that protocol, consumes only ``StageContext`` fields
that already existed, and expresses every outcome in the existing ``StageAction`` vocabulary. Rule
5 did not fire.

Sits beside ``AuthorizationStage`` and deliberately mirrors its shape, because the two answer
different questions about the same request and should be recognisably the same *kind* of control:

* ``AuthorizationStage`` - *may this principal do this?* (identity -> permissions)
* ``PolicyStage``        - *is this request permitted at all?* (deployment/organization policy)

Policy never resolves a permission and never re-checks authorization: two components answering one
question is how they drift apart. It also never routes, never selects a provider, never touches
budget or accounting, and never triggers a retry - none of which it *can* do, since
``gateway.adapters.pipeline`` cannot import the policy adapter's peers (import-linter, Slice 13)
and this stage holds nothing but a port.

## Fail closed, three ways

1. **Engine unavailable** - ``PolicyEngineUnavailableError`` becomes a block. A policy control that
   fails open is not a control (ADR-0009 row 1). Contrast the Slice-10 cache, which fails *open*:
   losing a cache costs speed, losing policy costs enforcement.
2. **Engine misbehaving** - anything that is not a ``PolicyVerdict``, and any exception the engine
   lets escape, becomes a block. A future remote engine can return a deserialized shape this
   process did not expect, and "unexpected" must not resolve to "allowed".
3. **No tenant** - a request with no ``organization_id`` cannot have organization policy applied to
   it, so it is blocked rather than evaluated against nothing. Same posture as
   ``AuthorizationStage`` refusing an unauthenticated request.

## Caller reason vs. audit annotations

The caller always receives the engine's generic ``reason`` - never the rule name, never the
threshold, never whether the block was a denial or an outage. All of that goes to ``annotations``
for the audit trail. An operator can therefore distinguish "policy denied 400 requests" from
"policy was down for 4 minutes", while a caller probing the boundary learns nothing about where it
sits.
"""

from __future__ import annotations

from typing import Any

from gateway.application.ports.pipeline import StageAction, StageContext, StageResult
from gateway.application.ports.policy import (
    REQUEST_PAYLOAD_KEY,
    PolicyEnginePort,
    PolicyEngineUnavailableError,
    PolicyQuery,
    PolicyVerdict,
)

_BLOCKED_REASON = "request rejected by policy"


class PolicyStage:
    """Blocks a request that deployment policy does not permit."""

    def __init__(self, engine: PolicyEnginePort, *, name: str = "policy") -> None:
        self._engine = engine
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _block(self, reason: str, **annotations: Any) -> StageResult:
        return StageResult(
            action=StageAction.BLOCK,
            reason=reason,
            annotations={"stage": self._name, **annotations},
        )

    async def before_request(self, context: StageContext) -> StageResult:
        if context.organization_id is None:
            # Organization policy cannot be applied without an organization. Evaluating against
            # "no tenant" would silently mean "no policy", which is the fail-open shape.
            return self._block(_BLOCKED_REASON, untenanted=True)

        payload = context.attributes.get(REQUEST_PAYLOAD_KEY) or {}
        if not isinstance(payload, dict):
            return self._block(_BLOCKED_REASON, malformed_payload=True)

        query = PolicyQuery(
            organization_id=context.organization_id,
            correlation_id=context.correlation_id,
            payload=payload,
        )

        try:
            verdict = await self._engine.evaluate(query)
        except PolicyEngineUnavailableError as exc:
            return self._block(_BLOCKED_REASON, policy_unavailable=True, detail=str(exc))
        except Exception as exc:
            return self._block(
                _BLOCKED_REASON,
                policy_error=True,
                detail=f"{type(exc).__name__}: {exc}",
            )

        if not isinstance(verdict, PolicyVerdict):
            # A remote engine can deserialize into something unexpected. "Unexpected" is not
            # "allowed".
            return self._block(
                _BLOCKED_REASON,
                malformed_verdict=True,
                detail=f"engine returned {type(verdict).__name__}",
            )

        if not verdict.allowed:
            return self._block(
                verdict.reason,
                policy_denied=True,
                rule=verdict.rule,
                **dict(verdict.detail),
            )

        return StageResult(
            action=StageAction.CONTINUE,
            annotations={"stage": self._name, "policy_allowed": True, "rule": verdict.rule},
        )
