"""Permission requirements - the **declaration** side of RBAC (ADR-0016 Slice 5).

`AuthorizationStage` denies a request that declares no permission requirement. That rule is only
defensible if something is unambiguously responsible for making the declaration, otherwise the
stage is enforcing a convention it invented and nobody else knows about.

## Ownership

* **Producer:** whoever constructs the ``StageContext`` - the delivery layer, from endpoint
  metadata, with the mapping itself supplied by the composition root. Declaring what an endpoint
  requires is a deployment decision, exactly like the MCP tool permissions in Slice 4, and for
  the same reason: a requirement that the enforcing component invents cannot be audited against
  anything.
* **Consumer:** ``AuthorizationStage``, and nothing else. It remains the sole interpreter of
  RBAC keys inside the opaque ``StageContext.attributes``.

Producing a value and interpreting it are different responsibilities. Several modules may call
``declare()``; only one may decide what the result means. That is why the keys live here rather
than staying private to the stage - a private constant would have made the stage the owner of a
contract it merely enforces.

This module deliberately contains no lookup, no route table and no registry. Mapping endpoints to
requirements is the composition root's job and it has no consumer yet (Rule 2).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

#: Key naming the permissions a request requires. Absent => the request was never classified.
REQUIRED_PERMISSIONS_KEY = "required_permissions"
#: Optional key naming the resource, used only for audit annotations.
RESOURCE_KEY = "resource"


@dataclass(frozen=True, slots=True)
class PermissionRequirement:
    """What one endpoint requires of its caller.

    An empty ``permissions`` tuple is a real declaration meaning "this endpoint requires no
    permission", which is different from declaring nothing at all. The distinction is the whole
    point: the first is a decision somebody made, the second is a decision nobody made.
    """

    permissions: tuple[str, ...] = ()
    resource: str | None = None

    @classmethod
    def of(cls, *permissions: str, resource: str | None = None) -> PermissionRequirement:
        return cls(permissions=tuple(permissions), resource=resource)

    def as_attributes(self) -> dict[str, Any]:
        """Render into the opaque ``StageContext.attributes`` fragment the stage consumes."""
        attributes: dict[str, Any] = {REQUIRED_PERMISSIONS_KEY: self.permissions}
        if self.resource is not None:
            attributes[RESOURCE_KEY] = self.resource
        return attributes


def declare(*permissions: str, resource: str | None = None) -> dict[str, Any]:
    """Convenience for producers.

    ``attributes = declare("chat:read", resource="POST /v1/chat")``
    """
    return PermissionRequirement.of(*permissions, resource=resource).as_attributes()


def undeclared(attributes: Iterable[str]) -> bool:
    """Whether a set of attribute keys carries no requirement declaration at all."""
    return REQUIRED_PERMISSIONS_KEY not in set(attributes)
