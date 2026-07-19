"""Unit of Work port (Backend_Implementation_Guide.md §7).

Defines one transactional boundary per use-case. Framework-free: it exposes no ORM
session type, so the application/domain never depend on SQLAlchemy. The concrete
``AsyncUnitOfWork`` adapter binds the tenant/RLS context and manages the transaction.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol


class UnitOfWork(Protocol):
    """Async transactional context. Rolls back on exit unless ``commit`` was called."""

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
