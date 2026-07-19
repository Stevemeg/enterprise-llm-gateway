"""Minimal PipelineStage implementation (ADR-0016 Rule 4).

Exists to prove the protocol is implementable and to give ordering/registration tests something
concrete. It performs no inspection and never blocks - deliberately trivial, not production
behaviour.
"""

from __future__ import annotations

from gateway.application.ports.pipeline import StageContext, StageResult


class NoOpPipelineStage:
    """A stage that always continues."""

    def __init__(self, name: str = "noop") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def before_request(self, context: StageContext) -> StageResult:
        return StageResult()

    async def after_response(self, context: StageContext) -> StageResult:
        return StageResult()

    async def on_error(self, context: StageContext, error: Exception) -> StageResult:
        return StageResult()
