"""Alembic async environment (Migration_Strategy.md).

Uses the same typed settings as the application so migrations and the app agree on the
database URL (no duplicate/secret config). Migrations are raw SQL (our canonical
``Schema.sql`` is the source of truth), so ``target_metadata`` is ``None`` — we do not
autogenerate from ORM models.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from gateway.config.settings import load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", load_settings().database.url)

target_metadata = None


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (``alembic upgrade --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)  # type: ignore[arg-type]
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    configuration = config.get_section(config.config_ini_section, {})
    engine = async_engine_from_config(configuration, prefix="sqlalchemy.", poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
