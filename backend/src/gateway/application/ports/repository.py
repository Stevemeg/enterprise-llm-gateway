"""Repository ports (Backend_Implementation_Guide.md §6).

Interfaces only — concrete repositories arrive with their aggregates in later
milestones and live in ``adapters/persistence``. Repositories return domain objects,
operate within a tenant-scoped Unit of Work, and never leak ORM rows.
"""

from __future__ import annotations

from typing import Protocol, TypeVar
from uuid import UUID

T = TypeVar("T")
T_contra = TypeVar("T_contra", contravariant=True)


class Repository(Protocol[T]):
    """Read/write access to an aggregate, scoped to the active Unit of Work."""

    async def get(self, entity_id: UUID) -> T | None: ...

    async def add(self, entity: T) -> None: ...


class AppendOnlyRepository(Protocol[T_contra]):
    """Append-only aggregates (e.g., usage_ledger, audit_event) — DB-DEC-06.

    Intentionally exposes no update/delete/read, mirroring the database grants that make
    these tables immutable (ADR-0009, NFR-SEC09).
    """

    async def append(self, entity: T_contra) -> None: ...
