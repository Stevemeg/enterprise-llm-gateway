"""Request/response pipeline seam (ADR-0016, Tier-1 invariant 5).

This single interception point is what lets policy, evaluation, safety, cost checks, reflection
and human approval be added later **without changing any provider, router or agent interface**.
An earlier draft treated Policy Engine and Evaluation Pipeline as separate foundational
invariants; they are not. Neither requires every interface to know it exists - both require one
stable seam. This is it.

Defines the protocol only. No stages, no pipeline runner, no execution (Rule 2: protocol before
implementation).

## Phase 5 M2: narrowed to ``before_request`` (ADR-0020, a deliberate Tier-1 contraction)

This protocol originally also declared ``after_response(context)`` and ``on_error(context, error)``.
Neither was ever invoked: ``RequestPipeline.admit`` calls ``before_request`` and nothing else, and
all four implementations returned an inert ``CONTINUE``. They survived Slices 1-21 and Phase 5 M1 -
the milestone most likely to need them - with zero call sites.

Streaming was the honest test and it *strengthened* the case rather than rescuing the hooks.
Streamed inferences are not evaluated because ``serve_stream`` returns while the stream is still
open, and a post-response stage hook looks like the fix but is not: ``after_response`` receives no
outcome, no response and no usage (``ports/evaluation.py`` records exactly this). Making it useful
would mean widening *this* Tier-1 protocol to carry a response - the Rule 5 event against Tier 1
that ADR-0016's freeze most directly forbids.

**Invariant 5 is unchanged in substance.** One stable interception point that lets policy,
evaluation, safety, cost checks, reflection and human approval be added without touching any
provider, router or agent interface - that is carried entirely by ``before_request`` +
``StageResult``. What was removed described behaviour the system never had, and a reader could
reasonably have concluded responses pass back through the chain. They do not.

Re-adding either method is a Rule 5 event that must name its active consumer first.
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
