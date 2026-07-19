"""Minimal BaseAgent implementation (ADR-0016 Rule 4).

Validates the lifecycle contract and gives conformance tests a concrete subject. Contributes a
reasoning step saying it did nothing - which is still an explanation, per invariant 3.
"""

from __future__ import annotations

from typing import Any

from gateway.domain.routing.models import ReasoningStep


class BaseAgentSkeleton:
    """A conforming agent that makes no decisions."""

    def __init__(self, name: str = "skeleton") -> None:
        self._name = name
        self.prepared = False

    @property
    def name(self) -> str:
        return self._name

    async def prepare(self) -> None:
        self.prepared = True

    async def contribute(self, context: dict[str, Any]) -> ReasoningStep:
        return ReasoningStep(agent=self._name, summary="no-op agent; no decision contributed")

    async def dispose(self) -> None:
        self.prepared = False
