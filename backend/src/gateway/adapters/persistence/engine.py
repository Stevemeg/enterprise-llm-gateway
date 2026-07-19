"""Async SQLAlchemy engine + session factory (ADR-0001/0002).

Production uses PostgreSQL via asyncpg with an explicit connection pool
(Query_Performance_Guide.md §12: transaction-scoped pooling, pre-ping). SQLite (async)
is supported for local/testing with a StaticPool so an in-memory database persists
across sessions within a process.

The factory takes primitives (not a settings object) so this adapter stays independent
of the composition root (Clean Architecture dependency rule, enforced by import-linter).
"""

from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def create_database_engine(
    *,
    url: str,
    echo: bool = False,
    pool_size: int = 20,
    max_overflow: int = 10,
    pool_timeout_seconds: float = 30.0,
    pool_recycle_seconds: int = 1800,
) -> AsyncEngine:
    """Create the async engine. Pooling is configured for Postgres; SQLite uses StaticPool."""
    if make_url(url).get_backend_name() == "sqlite":
        return create_async_engine(
            url,
            echo=echo,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout_seconds,
        pool_recycle=pool_recycle_seconds,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the engine. ``expire_on_commit=False`` keeps objects usable."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
