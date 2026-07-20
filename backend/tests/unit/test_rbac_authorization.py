"""RBAC tests (ADR-0016 Slice 5).

Fail-closed first, deliberately. Every path that could plausibly end in "allow by accident" -
unknown principal, unknown organization, unknown role, undeclared requirement, missing identity -
is asserted to deny before any success path is asserted at all.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from gateway.adapters.authorization.in_memory_resolver import InMemoryPermissionResolver
from gateway.adapters.authorization.null_resolver import NullPermissionResolver
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.application.authorization.requirements import (
    REQUIRED_PERMISSIONS_KEY,
    RESOURCE_KEY,
    PermissionRequirement,
    declare,
    undeclared,
)
from gateway.application.ports.authorization import PermissionResolver
from gateway.application.ports.pipeline import PipelineStage, StageAction, StageContext

ORG = uuid4()
OTHER_ORG = uuid4()
PRINCIPAL = uuid4()
STRANGER = uuid4()

ROLE_PERMISSIONS = {
    "viewer": ("chat:read",),
    "operator": ("chat:read", "chat:write"),
    "auditor": ("audit:read",),
}


def resolver() -> InMemoryPermissionResolver:
    r = InMemoryPermissionResolver(ROLE_PERMISSIONS)
    r.assign(ORG, PRINCIPAL, ["operator"])
    return r


def ctx(**overrides: Any) -> StageContext:
    attributes = overrides.pop("attributes", {REQUIRED_PERMISSIONS_KEY: ("chat:read",)})
    return StageContext(
        correlation_id="c-1",
        organization_id=overrides.pop("organization_id", ORG),
        principal_id=overrides.pop("principal_id", PRINCIPAL),
        attributes=attributes,
    )


# --------------------------------------------------------------------- fail closed (first)


async def test_unknown_principal_resolves_empty_and_blocks() -> None:
    """The headline requirement: unknown principal => empty permissions => BLOCK."""
    r = resolver()
    assert await r.resolve(STRANGER, ORG) == frozenset()

    result = await AuthorizationStage(r).before_request(ctx(principal_id=STRANGER))
    assert result.blocked is True
    assert result.action is StageAction.BLOCK
    assert result.reason


async def test_known_principal_in_wrong_organization_blocks() -> None:
    """Authority must not cross the tenant boundary RLS enforces at the storage layer."""
    r = resolver()
    assert await r.resolve(PRINCIPAL, OTHER_ORG) == frozenset()
    result = await AuthorizationStage(r).before_request(ctx(organization_id=OTHER_ORG))
    assert result.blocked is True


async def test_undeclared_requirement_blocks() -> None:
    """A route nobody classified is not a public route."""
    result = await AuthorizationStage(resolver()).before_request(ctx(attributes={}))
    assert result.blocked is True
    assert result.annotations["undeclared"] is True


@pytest.mark.parametrize(
    ("organization_id", "principal_id"), [(None, PRINCIPAL), (ORG, None), (None, None)]
)
async def test_missing_identity_blocks(organization_id: Any, principal_id: Any) -> None:
    result = await AuthorizationStage(resolver()).before_request(
        ctx(organization_id=organization_id, principal_id=principal_id)
    )
    assert result.blocked is True
    assert result.annotations["unauthenticated"] is True


async def test_null_resolver_denies_everything() -> None:
    """An unwired RBAC subsystem must deny every request, not allow every one."""
    stage = AuthorizationStage(NullPermissionResolver())
    assert (await stage.before_request(ctx())).blocked is True


async def test_partial_permissions_block() -> None:
    r = InMemoryPermissionResolver(ROLE_PERMISSIONS)
    r.assign(ORG, PRINCIPAL, ["viewer"])  # has chat:read, not chat:write
    result = await AuthorizationStage(r).before_request(
        ctx(attributes={REQUIRED_PERMISSIONS_KEY: ("chat:read", "chat:write")})
    )
    assert result.blocked is True
    assert result.annotations["missing_permissions"] == ("chat:write",)


async def test_dangling_role_assignment_narrows_never_widens() -> None:
    r = InMemoryPermissionResolver(ROLE_PERMISSIONS)
    r.assign(ORG, PRINCIPAL, ["operator", "role-that-was-deleted"])
    assert await r.resolve(PRINCIPAL, ORG) == frozenset({"chat:read", "chat:write"})


async def test_denial_reason_never_names_the_missing_permission() -> None:
    """The reason reaches the caller; the detail belongs to the audit trail only."""
    r = InMemoryPermissionResolver(ROLE_PERMISSIONS)
    r.assign(ORG, PRINCIPAL, ["viewer"])
    result = await AuthorizationStage(r).before_request(
        ctx(attributes={REQUIRED_PERMISSIONS_KEY: ("billing:admin",)})
    )
    assert "billing:admin" not in (result.reason or "")
    assert result.annotations["missing_permissions"] == ("billing:admin",)


# --------------------------------------------------------------------- allow paths


async def test_exact_permission_allows() -> None:
    result = await AuthorizationStage(resolver()).before_request(ctx())
    assert result.action is StageAction.CONTINUE
    assert result.annotations["authorized"] is True


async def test_superset_of_permissions_allows() -> None:
    result = await AuthorizationStage(resolver()).before_request(
        ctx(attributes={REQUIRED_PERMISSIONS_KEY: ("chat:read", "chat:write")})
    )
    assert result.action is StageAction.CONTINUE


async def test_empty_requirement_tuple_is_declared_and_allows() -> None:
    """Declaring "this needs nothing" differs from declaring nothing at all."""
    result = await AuthorizationStage(resolver()).before_request(
        ctx(attributes={REQUIRED_PERMISSIONS_KEY: ()})
    )
    assert result.action is StageAction.CONTINUE


async def test_bare_string_requirement_is_one_permission_not_five_characters() -> None:
    r = InMemoryPermissionResolver({"viewer": ("admin",)})
    r.assign(ORG, PRINCIPAL, ["viewer"])
    result = await AuthorizationStage(r).before_request(
        ctx(attributes={REQUIRED_PERMISSIONS_KEY: "admin"})
    )
    assert result.action is StageAction.CONTINUE


async def test_resource_is_annotated_for_audit() -> None:
    result = await AuthorizationStage(resolver()).before_request(
        ctx(attributes={REQUIRED_PERMISSIONS_KEY: ("chat:read",), RESOURCE_KEY: "POST /v1/chat"})
    )
    assert result.annotations["resource"] == "POST /v1/chat"


# --------------------------------------------------------------------- protocol conformance


async def test_stage_satisfies_the_pipeline_protocol_unchanged() -> None:
    assert isinstance(AuthorizationStage(NullPermissionResolver()), PipelineStage)


@pytest.mark.parametrize(
    "impl", [NullPermissionResolver(), InMemoryPermissionResolver()], ids=["null", "in_memory"]
)
async def test_resolvers_satisfy_the_port(impl: PermissionResolver) -> None:
    assert isinstance(impl, PermissionResolver)
    assert await impl.resolve(uuid4(), uuid4()) == frozenset()


async def test_lifecycle_methods_never_reauthorize() -> None:
    stage = AuthorizationStage(resolver())
    assert (await stage.after_response(ctx())).action is StageAction.CONTINUE
    assert (await stage.on_error(ctx(), RuntimeError("downstream"))).action is StageAction.CONTINUE


# --------------------------------------------------------------------- declaration ownership


async def test_declared_requirement_is_what_the_stage_consumes() -> None:
    """The producer declares; the stage consumes. No hidden convention in between."""
    attributes = declare("chat:read", resource="POST /v1/chat")
    result = await AuthorizationStage(resolver()).before_request(ctx(attributes=attributes))
    assert result.action is StageAction.CONTINUE
    assert result.annotations["resource"] == "POST /v1/chat"


async def test_declaring_no_permissions_differs_from_declaring_nothing() -> None:
    declared_empty = declare()
    assert undeclared(declared_empty) is False
    assert undeclared({}) is True

    allowed = await AuthorizationStage(resolver()).before_request(ctx(attributes=declared_empty))
    denied = await AuthorizationStage(resolver()).before_request(ctx(attributes={}))
    assert allowed.action is StageAction.CONTINUE
    assert denied.blocked is True


async def test_requirement_renders_only_the_keys_it_declares() -> None:
    assert PermissionRequirement.of("a", "b").as_attributes() == {
        REQUIRED_PERMISSIONS_KEY: ("a", "b")
    }
    assert RESOURCE_KEY not in PermissionRequirement.of("a").as_attributes()
