"""Database health-check behaviour, including the failure mode (ADR-0009)."""

from __future__ import annotations

import pytest

from gateway.adapters.persistence.engine import create_database_engine
from gateway.adapters.persistence.health import DatabaseHealthCheck

pytestmark = pytest.mark.integration


async def test_healthy_when_reachable() -> None:
    engine = create_database_engine(url="sqlite+aiosqlite:///:memory:")
    result = await DatabaseHealthCheck(engine)()
    assert result.healthy is True
    await engine.dispose()


async def test_unhealthy_when_unreachable() -> None:
    engine = create_database_engine(url="sqlite+aiosqlite:////no_such_dir/missing.db")
    result = await DatabaseHealthCheck(engine)()
    assert result.healthy is False
    assert "unreachable" in (result.detail or "")
    await engine.dispose()
