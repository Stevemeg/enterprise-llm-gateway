"""Request/response pipeline seam (ADR-0016, Tier-1 invariant 5).

This single interception point is what lets policy, evaluation, safety, cost checks, reflection
and human approval be added later **without changing any provider, router or agent interface**.
An earlier draft treated Policy Engine and Evaluation Pipeline as separate foundational
invariants; they are not. Neither requires every interface to know it exists - both require one
stable seam. This is it.

Defines the protocol only. No stages, no pipeline runner, no execution (Rule 2: protocol before
implementation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID


class StageAction(StrEnum):
    """What a stage decided. Closed vocabulary - safe as a metric label."""

    CONTINUE = "continue"
    ANNOTATE = "annotate"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class StageContext:
    """What a stage may inspect. Carries identity and correlation, never raw credentials."""

    correlation_id: str
    organization_id: UUID | None = None
    principal_id: UUID | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StageResult:
    """A stage's verdict.

    ``BLOCK`` must carry a ``reason``: a stage that blocks without saying why produces an
    unexplainable denial, which is the failure mode the routing invariant also guards against.
    """

    action: StageAction = StageAction.CONTINUE
    reason: str | None = None
    annotations: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.action is StageAction.BLOCK


@runtime_checkable
class PipelineStage(Protocol):
    """A pluggable interception point around a request.

    ``runtime_checkable`` so conformance can be asserted structurally in tests - matching
    ``BaseAgent``. A class that merely *looks* like a stage but omits a method would otherwise
    import cleanly and fail at the call site.

    Stages must not import providers: a stage that reaches a provider directly has bypassed the
    router and the decision record (CI-enforced).
    """

    @property
    def name(self) -> str:
        """Stable identifier used in ordering, metrics and audit."""
        ...

    async def before_request(self, context: StageContext) -> StageResult: ...

    async def after_response(self, context: StageContext) -> StageResult: ...

    async def on_error(self, context: StageContext, error: Exception) -> StageResult: ...
