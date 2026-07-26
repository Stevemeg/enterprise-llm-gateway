"""RBAC enforcement as a PipelineStage (ADR-0016 Slice 5) - a pure consumer of Tier-1.

Implements ``PipelineStage`` unchanged and consumes the RBAC-owned ``PermissionResolver``. It is
the **only** component permitted to interpret RBAC keys inside ``StageContext.attributes``:
``attributes`` is opaque by contract, and a second reader would make its meaning a shared
assumption rather than one component's private convention.

## Why an undeclared request is denied

If ``attributes`` carries no requirement key, the stage denies. That is deliberate and it is the
uncomfortable choice, because it means an unlabelled route stops working the moment this stage is
wired in.

The alternative - allow what we cannot classify - is how authorization gaps ship. A route whose
requirements nobody declared is not a public route; it is a route nobody thought about. Failing
loudly at wiring time surfaces that during development, whereas failing open surfaces it during
an incident. This is the same trade the MCP adapter could not make in Slice 4, where an
unconfigured tool defaults to open; here the decision is ours to take, so we take it.

Denials never name the missing permission. Telling an unauthorized caller precisely which
permission to acquire is a reconnaissance aid, and the reason string is returned to the caller.
The full detail goes to ``annotations`` for the audit trail instead.
"""

from __future__ import annotations

from typing import Any

from gateway.application.authorization.requirements import (
    REQUIRED_PERMISSIONS_KEY,
    RESOURCE_KEY,
)
from gateway.application.ports.authorization import PermissionResolver
from gateway.application.ports.pipeline import StageAction, StageContext, StageResult


class AuthorizationStage:
    """Blocks a request unless its principal holds every permission the request declares."""

    def __init__(self, resolver: PermissionResolver) -> None:
        self._resolver = resolver

    @property
    def name(self) -> str:
        return "authorization"

    def _required(self, attributes: dict[str, Any]) -> frozenset[str] | None:
        """The declared requirement, or ``None`` when the request declared nothing."""
        raw = attributes.get(REQUIRED_PERMISSIONS_KEY)
        if raw is None:
            return None
        if isinstance(raw, str):
            # A bare string is almost always a mistake ("admin" would otherwise become the
            # permission set {'a','d','m','i','n'}), so treat it as the single permission meant.
            return frozenset({raw})
        if isinstance(raw, (list, tuple, set, frozenset)):
            return frozenset(str(item) for item in raw)
        return frozenset({str(raw)})

    def _deny(self, reason: str, **annotations: Any) -> StageResult:
        return StageResult(action=StageAction.BLOCK, reason=reason, annotations=annotations)

    async def before_request(self, context: StageContext) -> StageResult:
        resource = context.attributes.get(RESOURCE_KEY)
        required = self._required(context.attributes)

        if required is None:
            return self._deny(
                "request declares no permission requirement",
                stage=self.name,
                resource=resource,
                undeclared=True,
            )
        if context.organization_id is None or context.principal_id is None:
            # No identity means nothing to resolve against. Anonymous access, if it is ever
            # wanted, must be an explicit declaration rather than a missing field.
            return self._deny(
                "unauthenticated request", stage=self.name, resource=resource, unauthenticated=True
            )

        granted = await self._resolver.resolve(context.principal_id, context.organization_id)
        missing = required - granted
        if missing:
            return self._deny(
                "principal lacks the required permissions",
                stage=self.name,
                resource=resource,
                # Audit-side only; the caller sees `reason`, never this.
                missing_permissions=tuple(sorted(missing)),
            )
        return StageResult(
            action=StageAction.CONTINUE,
            annotations={"stage": self.name, "authorized": True, "resource": resource},
        )
