"""PostgreSQL-backed ResponseCachePort (ADR-0016 Slice 10, ADR-0018).

Persists into the pre-existing ``semantic_cache_entry`` table (see ``adapters/persistence/
cache_tables.py`` for why no new migration was needed). RLS was already enabled+forced on this
table in ``0001_initial.sql`` (tenant-isolation policy made NULLIF-safe by every tenant table's
``0005_rls_nullif_org_guc.sql`` rewrite) and ``app_rw`` already holds full SELECT/INSERT/UPDATE/
DELETE on it (``0003_database_roles.sql`` grants DML on all tables; nothing revoked it - a cache,
unlike ``cost_ledger``, is not append-only, and a repeat write for the same key is an ordinary
refresh, not a defect).

Fails **open**, not closed (contrast ``SqlBudgetLedger``): any unexpected database error is
translated to ``CacheUnavailableError`` here, but ``InferenceCoordinator`` - not this adapter - is
what decides to treat that as an ordinary miss on read or a dropped write on write. A malformed
stored entry (a row this process cannot parse back into a ``CachedResponse``) is returned as
``None`` directly, not raised - it is a stale/foreign-write concern, not an availability concern,
and must never propagate as an error a caller would have to specifically handle to get "no hit".

``organization_id`` is filtered explicitly in every query despite RLS already restricting rows -
defence in depth, and the same double-layer style ``SqlBudgetLedger`` already uses.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from gateway.adapters.persistence.cache_tables import semantic_cache_entry
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.application.ports.cache import CachedResponse, CacheKey, CacheUnavailableError
from gateway.shared.clock import Clock

_DEFAULT_TTL = timedelta(hours=1)


class SqlResponseCache:
    """Durable, tenant-scoped, TTL-expiring exact-match cache against real PostgreSQL."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, *, ttl: timedelta = _DEFAULT_TTL
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ttl = ttl

    async def get(self, organization_id: UUID, key: CacheKey) -> CachedResponse | None:
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                row = (
                    (
                        await uow.session.execute(
                            select(
                                semantic_cache_entry.c.response,
                                semantic_cache_entry.c.expires_at,
                            ).where(
                                semantic_cache_entry.c.organization_id == organization_id,
                                semantic_cache_entry.c.request_hash == key.digest,
                            )
                        )
                    )
                    .mappings()
                    .first()
                )
                await uow.commit()
        except (SQLAlchemyError, OSError) as exc:
            # OSError covers a raw connection refusal (e.g. ConnectionRefusedError) that can
            # surface unwrapped, before SQLAlchemy's own exception translation applies - a
            # database that refuses the TCP connection outright is exactly as unavailable as
            # one that accepts the connection and then errors (mirrors SqlBudgetLedger).
            raise CacheUnavailableError(str(exc)) from exc

        if row is None:
            return None
        expires_at = row["expires_at"]
        if expires_at is not None and expires_at <= self._clock.now():
            return None  # expired - treated exactly like a miss, no eager delete needed
        payload = row["response"]
        try:
            return CachedResponse(
                provider=payload["provider"], model=payload["model"], content=payload["content"]
            )
        except (KeyError, TypeError):
            return None  # malformed stored entry - fail open to a miss, never raise or serve it

    async def put(self, organization_id: UUID, key: CacheKey, response: CachedResponse) -> None:
        payload = {
            "provider": response.provider,
            "model": response.model,
            "content": response.content,
        }
        expires_at = self._clock.now() + self._ttl
        try:
            async with self._uow_factory(tenant_id=organization_id) as uow:
                await uow.session.execute(
                    pg_insert(semantic_cache_entry)
                    .values(
                        id=uuid4(),
                        organization_id=organization_id,
                        request_hash=key.digest,
                        response=payload,
                        expires_at=expires_at,
                    )
                    .on_conflict_do_update(
                        index_elements=["organization_id", "request_hash"],
                        set_={"response": payload, "expires_at": expires_at},
                    )
                )
                await uow.commit()
        except (SQLAlchemyError, OSError) as exc:
            # OSError covers a raw connection refusal (e.g. ConnectionRefusedError) that can
            # surface unwrapped, before SQLAlchemy's own exception translation applies - a
            # database that refuses the TCP connection outright is exactly as unavailable as
            # one that accepts the connection and then errors (mirrors SqlBudgetLedger).
            raise CacheUnavailableError(str(exc)) from exc
