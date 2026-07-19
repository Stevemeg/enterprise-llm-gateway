"""Unit-of-Work transaction lifecycle against real SQLite (Postgres verified in CI)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.uow import UnitOfWorkFactory

pytestmark = pytest.mark.integration


async def _make_factory(tmp_path: Path) -> tuple[UnitOfWorkFactory, AsyncEngine]:
    engine = create_database_engine(url=f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE item (id INTEGER PRIMARY KEY, name TEXT)"))
    return UnitOfWorkFactory(create_session_factory(engine), rls_enabled=False), engine


async def _count(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT count(*) FROM item"))
        return int(result.scalar_one())


async def test_commit_persists(tmp_path: Path) -> None:
    factory, engine = await _make_factory(tmp_path)
    async with factory(tenant_id=None) as uow:
        await uow.session.execute(text("INSERT INTO item (name) VALUES ('x')"))
        await uow.commit()
    assert await _count(engine) == 1
    await engine.dispose()


async def test_rollback_on_error_discards(tmp_path: Path) -> None:
    factory, engine = await _make_factory(tmp_path)

    async def _insert_then_fail() -> None:
        async with factory() as uow:
            await uow.session.execute(text("INSERT INTO item (name) VALUES ('y')"))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await _insert_then_fail()
    assert await _count(engine) == 0
    await engine.dispose()


async def test_session_unavailable_outside_context(tmp_path: Path) -> None:
    factory, engine = await _make_factory(tmp_path)
    uow = factory()
    with pytest.raises(RuntimeError, match="outside of an async context"):
        _ = uow.session
    await engine.dispose()
