"""Policy engine seam (ADR-0016 Slice 13) - a **capability-owned** port, not a Tier-1 protocol.

ADR-0016 demoted Policy Engine from Tier 1 on the claim that policy should consume the stable
pipeline seam rather than requiring every interface to know policy exists. This slice tests that
claim and it holds: ``PolicyStage`` implements ``PipelineStage`` **unchanged**, reads only
``StageContext`` fields that already exist, and expresses its verdict entirely in the existing
``StageAction`` vocabulary. Rule 5 was not triggered against Tier 1 or any capability-owned port.

## Three policy-ish things now exist, and they answer different questions

* **RBAC** (``AuthorizationStage`` + ``PermissionResolver``, Slice 5) - *"may this **principal**
  perform this action?"* Identity resolved to a permission set, compared against a declared
  requirement. Policy Engine does not resolve permissions and never will: duplicating that would
  give the system two answers to one question.
* **PolicyAgent** (inside ``AgentRuntime``, Slice 2/6) - *"which **providers/regions** is this
  request eligible for?"* Routing-time provider eligibility, contributed into ``RoutingDecision``
  as part of the routing explanation.
* **Policy Engine** (this slice) - *"is this **request** permitted by deployment/organization
  policy at all?"* Identity-independent and provider-independent, decided before anything runs.

The first policy - a maximum request size - sits cleanly in the third bucket: it is not about who
is asking (RBAC) and not about which provider would serve it (PolicyAgent).

## Fail-closed, and outage is distinguishable from denial

An engine that cannot answer raises ``PolicyEngineUnavailableError``. ``PolicyStage`` catches it
and **blocks** (ADR-0009 row 1: a policy control that fails open is not a control). The two are
never conflated in the record even though both block: the caller sees the same generic reason
either way, while the audit annotations carry ``policy_unavailable=True`` for an outage and the
deciding rule for a genuine denial. Collapsing them would make a policy outage indistinguishable
from a spike in legitimate denials on exactly the dashboard an operator would use to tell them
apart.

## Caller reason vs. audit detail

``reason`` is caller-visible and deliberately generic. ``rule`` and ``detail`` are audit-only.
This mirrors ``AuthorizationStage``, which refuses to name the missing permission to the caller
because telling an unauthorized caller precisely which control stopped them is a reconnaissance
aid - the same argument applies to naming which policy rule fired and what its threshold is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

#: Key under which the inbound request payload appears in ``StageContext.attributes``.
#: This is not a new convention - ``AgentRoutingStage`` (Slice 6) already reads ``"request"`` from
#: attributes for the same purpose. It is named here so the policy capability consumes a declared
#: constant rather than a second magic string, and so the shared meaning is written down once.
#: Both readers agree on what it *is* (the inbound payload); neither reinterprets it.
REQUEST_PAYLOAD_KEY = "request"


class PolicyEffect(StrEnum):
    """What policy decided (closed vocabulary, safe as a metric label).

    Only two members. An ``UNAVAILABLE`` effect deliberately does not exist: an engine that could
    not decide has not produced an effect at all, and modelling "no answer" as a kind of answer is
    what lets an outage quietly become a verdict. Unavailability is an exception, handled by the
    stage, exactly as ``LedgerUnavailableError`` and ``BudgetUnavailableError`` already are.
    """

    ALLOW = "allow"
    DENY = "deny"


class PolicyEngineUnavailableError(RuntimeError):
    """The policy engine could not reach a decision.

    Never a verdict. ``PolicyStage`` converts this into a **block** (fail closed), mirroring
    ``BudgetEnforcer``/``ReservationService`` on their own store outages. Contrast
    ``CacheUnavailableError``, which fails *open* - a cache outage costs speed, a policy outage
    would cost enforcement.
    """


@dataclass(frozen=True, slots=True)
class PolicyQuery:
    """What the engine is asked to decide about.

    Deliberately narrow (Rule 5). No ``principal_id``: the first policy is identity-independent,
    and RBAC already owns identity questions - adding the field "because a future policy might
    want it" is the speculative accumulation Rule 5 exists to prevent. No provider or model:
    ``PolicyAgent`` owns provider eligibility. No evaluation results: nothing in this slice
    consumes them, and coupling policy to Slice 12 without a consumer would bind two capabilities
    that are meant to stay independent.
    """

    organization_id: UUID
    correlation_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyVerdict:
    """One policy decision.

    ``reason`` is caller-visible and must be generic. ``rule`` and ``detail`` are audit-only and
    may name the specific control and its measurements. A ``DENY`` must carry a reason - an
    unexplained denial is exactly the unauditable outcome ``StageResult`` already forbids for
    ``BLOCK`` and ``RoutingDecision`` forbids for a routing refusal.
    """

    effect: PolicyEffect
    reason: str = ""
    rule: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.effect is PolicyEffect.DENY and not self.reason:
            raise ValueError("a DENY verdict must carry a caller-visible reason")

    @property
    def allowed(self) -> bool:
        return self.effect is PolicyEffect.ALLOW


@runtime_checkable
class PolicyEnginePort(Protocol):
    """Decides whether a request is permitted by deployment/organization policy."""

    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        """Return a verdict, or raise ``PolicyEngineUnavailableError`` if none can be reached.

        Must never return ``ALLOW`` to signal "I could not decide" - that is precisely the
        failure mode the separate exception exists to make impossible to express.
        """
        ...
