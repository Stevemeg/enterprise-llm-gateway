"""Async Unit of Work (Backend_Implementation_Guide.md §7, ADR-0002/0004).

Wraps a single transaction. On enter it opens a session and — for PostgreSQL — binds
the tenant RLS context; on exit it rolls back if an exception propagated, then closes.
No provider/network call belongs inside this boundary (ADR-0004). RLS binding is
skipped for non-Postgres engines (local SQLite tests) where ``set_config`` is absent.
"""

from __future__ import annotations

from types import TracebackType
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gateway.adapters.persistence.rls import bind_tenant


class AsyncUnitOfWork:
    """A transactional unit bound to one tenant (or none, for system operations)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        tenant_id: UUID | None,
        rls_enabled: bool,
    ) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._rls_enabled = rls_enabled
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork.session accessed outside of an async context")
        return self._session

    async def __aenter__(self) -> AsyncUnitOfWork:
        session = self._session_factory()
        self._session = session
        if self._rls_enabled and self._tenant_id is not None:
            await bind_tenant(session, self._tenant_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            if exc_type is not None:
                await session.rollback()
        finally:
            await session.close()
            self._session = None

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


class UnitOfWorkFactory:
    """Creates tenant-scoped Units of Work. Wired once in the composition root."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, rls_enabled: bool
    ) -> None:
        self._session_factory = session_factory
        self._rls_enabled = rls_enabled

    def __call__(self, *, tenant_id: UUID | None = None) -> AsyncUnitOfWork:
        return AsyncUnitOfWork(
            self._session_factory, tenant_id=tenant_id, rls_enabled=self._rls_enabled
        )
