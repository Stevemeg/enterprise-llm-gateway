"""Database health check (NFR-O03, ADR-0009).

Runs ``SELECT 1`` against the pool. A failure is reported as DOWN (never raised), so the
health endpoint reflects dependency state without crashing.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.application.ports.health import CheckResult


class DatabaseHealthCheck:
    """Callable health check for the primary database."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def __call__(self) -> CheckResult:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception as exc:  # report, never crash health reporting
            return CheckResult(healthy=False, detail=f"database unreachable: {exc!s}")
        return CheckResult(healthy=True, detail="ok")
