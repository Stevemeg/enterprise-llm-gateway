"""LocalPolicyEngine and PolicyStage tests (ADR-0016 Slice 13).

Fail-safe paths first: what policy *refuses to allow* matters more than what it allows, because
every failure mode here defaults toward enforcement (ADR-0009 row 1) and a single fail-open path
would silently disable the control.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.application.ports.pipeline import PipelineStage, StageAction, StageContext
from gateway.application.ports.policy import (
    REQUEST_PAYLOAD_KEY,
    PolicyEffect,
    PolicyEnginePort,
    PolicyEngineUnavailableError,
    PolicyQuery,
    PolicyVerdict,
)

ORG = uuid4()


class UnavailableEngine:
    """An engine that cannot reach a decision."""

    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        raise PolicyEngineUnavailableError("policy backend unreachable")


class ExplodingEngine:
    """An engine with a defect - it raises something other than the declared outage error."""

    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        raise RuntimeError("engine is broken")


class MalformedEngine:
    """A misbehaving engine returning a shape this process did not expect."""

    async def evaluate(self, query: PolicyQuery) -> object:
        return {"effect": "allow"}


class AllowAllEngine:
    async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
        return PolicyVerdict(effect=PolicyEffect.ALLOW, rule="allow_all")


def _context(
    *, organization_id: object = ORG, payload: object | None = None, **attrs: object
) -> StageContext:
    attributes: dict[str, object] = dict(attrs)
    if payload is not None:
        attributes[REQUEST_PAYLOAD_KEY] = payload
    return StageContext(
        correlation_id="c1",
        organization_id=organization_id,  # type: ignore[arg-type]
        principal_id=uuid4(),
        attributes=attributes,
    )


def _query(payload: dict[str, object] | None = None) -> PolicyQuery:
    return PolicyQuery(
        organization_id=ORG, correlation_id="c1", payload=payload if payload is not None else {}
    )


# ------------------------------------------------------------------ engine: deterministic verdicts


async def test_a_small_request_is_allowed() -> None:
    verdict = await LocalPolicyEngine().evaluate(_query({"prompt": "hello"}))

    assert verdict.effect is PolicyEffect.ALLOW
    assert verdict.allowed is True


async def test_an_oversized_request_is_denied() -> None:
    engine = LocalPolicyEngine(max_request_bytes=64)

    verdict = await engine.evaluate(_query({"prompt": "x" * 500}))

    assert verdict.effect is PolicyEffect.DENY
    assert verdict.allowed is False
    assert verdict.rule == "max_request_bytes"


async def test_the_limit_boundary_is_inclusive() -> None:
    """A request exactly at the limit is permitted; one byte more is not."""
    engine = LocalPolicyEngine(max_request_bytes=20)
    at_limit = _query({"a": "bcdefghijklm"})  # {"a":"bcdefghijklm"} == 20 bytes
    assert len(str(at_limit.payload)) > 0

    allowed = await engine.evaluate(at_limit)
    denied = await engine.evaluate(_query({"a": "bcdefghijklmn"}))

    assert allowed.effect is PolicyEffect.ALLOW
    assert denied.effect is PolicyEffect.DENY


async def test_verdicts_are_deterministic_regardless_of_dict_ordering() -> None:
    engine = LocalPolicyEngine(max_request_bytes=64)

    first = await engine.evaluate(_query({"a": 1, "b": 2, "c": 3}))
    second = await engine.evaluate(_query({"c": 3, "a": 1, "b": 2}))

    assert first == second


async def test_an_unmeasurable_payload_is_denied_not_waved_through() -> None:
    """A payload that cannot be canonically encoded cannot be measured, and a limit that cannot
    be measured has not been satisfied."""
    verdict = await LocalPolicyEngine().evaluate(_query({"bad": object()}))

    assert verdict.effect is PolicyEffect.DENY
    assert verdict.detail["unmeasurable_payload"] is True


def test_a_nonsensical_limit_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        LocalPolicyEngine(max_request_bytes=0)


def test_a_deny_verdict_must_carry_a_caller_reason() -> None:
    with pytest.raises(ValueError, match="must carry a caller-visible reason"):
        PolicyVerdict(effect=PolicyEffect.DENY, reason="")


def test_the_engine_satisfies_its_port() -> None:
    assert isinstance(LocalPolicyEngine(), PolicyEnginePort)


# ------------------------------------------------------------------ stage: protocol conformance


def test_the_policy_stage_satisfies_the_tier_1_pipeline_protocol_unchanged() -> None:
    """ADR-0016's Tier-2 hypothesis: policy consumes PipelineStage without altering it."""
    assert isinstance(PolicyStage(LocalPolicyEngine()), PipelineStage)


# ------------------------------------------------------------------ stage: allow / deny


async def test_an_allowed_request_continues() -> None:
    stage = PolicyStage(LocalPolicyEngine())

    result = await stage.before_request(_context(payload={"prompt": "hi"}))

    assert result.action is StageAction.CONTINUE
    assert result.blocked is False
    assert result.annotations["policy_allowed"] is True


async def test_a_denied_request_blocks_with_an_auditable_reason() -> None:
    stage = PolicyStage(LocalPolicyEngine(max_request_bytes=32))

    result = await stage.before_request(_context(payload={"prompt": "x" * 500}))

    assert result.action is StageAction.BLOCK
    assert result.blocked is True
    assert result.reason
    assert result.annotations["policy_denied"] is True
    assert result.annotations["rule"] == "max_request_bytes"


async def test_the_caller_reason_does_not_leak_the_rule_or_threshold() -> None:
    """Telling a caller exactly which control stopped them and where its limit sits is a
    reconnaissance aid - the same reasoning AuthorizationStage applies to permission names."""
    stage = PolicyStage(LocalPolicyEngine(max_request_bytes=32))

    result = await stage.before_request(_context(payload={"prompt": "x" * 500}))

    assert result.reason is not None
    assert "max_request_bytes" not in result.reason
    assert "32" not in result.reason
    assert "byte" not in result.reason.lower()
    # ...while the audit annotations retain everything an operator needs.
    assert result.annotations["limit_bytes"] == 32
    assert result.annotations["request_bytes"] > 32


# ------------------------------------------------------------------ stage: fail closed


async def test_an_unavailable_engine_blocks_rather_than_allowing() -> None:
    """A policy control that fails open is not a control (ADR-0009 row 1)."""
    stage = PolicyStage(UnavailableEngine())

    result = await stage.before_request(_context(payload={"prompt": "hi"}))

    assert result.action is StageAction.BLOCK
    assert result.annotations["policy_unavailable"] is True


async def test_an_outage_is_distinguishable_from_a_denial_in_the_audit_trail() -> None:
    """Both block, but an operator must be able to tell a policy outage from a denial spike."""
    denied = await PolicyStage(LocalPolicyEngine(max_request_bytes=8)).before_request(
        _context(payload={"prompt": "x" * 500})
    )
    unavailable = await PolicyStage(UnavailableEngine()).before_request(
        _context(payload={"prompt": "hi"})
    )

    assert denied.annotations.get("policy_denied") is True
    assert denied.annotations.get("policy_unavailable") is None
    assert unavailable.annotations.get("policy_unavailable") is True
    assert unavailable.annotations.get("policy_denied") is None
    # The caller cannot tell them apart, which is deliberate.
    assert denied.reason == unavailable.reason


async def test_an_engine_that_raises_unexpectedly_blocks() -> None:
    stage = PolicyStage(ExplodingEngine())

    result = await stage.before_request(_context(payload={"prompt": "hi"}))

    assert result.action is StageAction.BLOCK
    assert result.annotations["policy_error"] is True
    assert "RuntimeError" in result.annotations["detail"]


async def test_a_malformed_verdict_blocks_rather_than_being_treated_as_allow() -> None:
    stage = PolicyStage(MalformedEngine())  # type: ignore[arg-type]

    result = await stage.before_request(_context(payload={"prompt": "hi"}))

    assert result.action is StageAction.BLOCK
    assert result.annotations["malformed_verdict"] is True


async def test_a_request_without_a_tenant_blocks() -> None:
    """Organization policy cannot be applied without an organization; evaluating against no tenant
    would silently mean no policy."""
    stage = PolicyStage(AllowAllEngine())

    result = await stage.before_request(_context(organization_id=None, payload={"prompt": "hi"}))

    assert result.action is StageAction.BLOCK
    assert result.annotations["untenanted"] is True


async def test_a_malformed_payload_attribute_blocks() -> None:
    stage = PolicyStage(AllowAllEngine())

    result = await stage.before_request(_context(payload="not-a-dict"))

    assert result.action is StageAction.BLOCK
    assert result.annotations["malformed_payload"] is True


async def test_a_missing_payload_is_evaluated_as_empty_not_skipped() -> None:
    """An absent payload is still evaluated - policy is not bypassed by omitting the key."""
    stage = PolicyStage(LocalPolicyEngine())

    result = await stage.before_request(_context())

    assert result.action is StageAction.CONTINUE
    assert result.annotations["policy_allowed"] is True


# ------------------------------------------------------------------ stage: tenancy / boundaries


async def test_tenant_context_reaches_the_engine_unchanged() -> None:
    seen: list[PolicyQuery] = []

    class RecordingEngine:
        async def evaluate(self, query: PolicyQuery) -> PolicyVerdict:
            seen.append(query)
            return PolicyVerdict(effect=PolicyEffect.ALLOW, rule="recording")

    await PolicyStage(RecordingEngine()).before_request(_context(payload={"prompt": "hi"}))

    assert len(seen) == 1
    assert seen[0].organization_id == ORG
    assert seen[0].correlation_id == "c1"


async def test_responses_are_not_re_evaluated() -> None:
    stage = PolicyStage(LocalPolicyEngine(max_request_bytes=1))

    result = await stage.after_response(_context(payload={"prompt": "x" * 500}))

    assert result.action is StageAction.CONTINUE, "policy decides before the request runs"


async def test_a_downstream_error_is_not_turned_into_a_policy_block() -> None:
    """Converting an unrelated failure into a policy decision would put a decision nobody made
    into the audit trail."""
    stage = PolicyStage(LocalPolicyEngine())

    result = await stage.on_error(_context(payload={"prompt": "hi"}), RuntimeError("downstream"))

    assert result.action is StageAction.CONTINUE


async def test_policy_does_not_resolve_permissions_or_consult_rbac() -> None:
    """RBAC and policy answer different questions; the stage carries no resolver and reads no
    RBAC keys, so a request with no permission declaration is still policy-evaluated normally."""
    stage = PolicyStage(LocalPolicyEngine())

    result = await stage.before_request(_context(payload={"prompt": "hi"}))

    assert result.action is StageAction.CONTINUE
    assert "missing_permissions" not in result.annotations
    assert "authorized" not in result.annotations
