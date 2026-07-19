"""Tests for the async engine factory and pool configuration."""

from __future__ import annotations

from sqlalchemy.pool import QueuePool, StaticPool

from gateway.adapters.persistence.engine import create_database_engine, create_session_factory


def test_postgres_engine_applies_pool_config() -> None:
    engine = create_database_engine(
        url="postgresql+asyncpg://u:p@host:5432/db", pool_size=7, max_overflow=3
    )
    assert engine.dialect.name == "postgresql"
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.size() == 7


def test_sqlite_engine_uses_static_pool() -> None:
    engine = create_database_engine(url="sqlite+aiosqlite:///:memory:")
    assert isinstance(engine.pool, StaticPool)


def test_session_factory_is_bound() -> None:
    engine = create_database_engine(url="sqlite+aiosqlite:///:memory:")
    factory = create_session_factory(engine)
    session = factory()
    assert session.bind is engine
