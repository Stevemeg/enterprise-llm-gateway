#!/usr/bin/env python3
"""Gate-2 bypass containment: the runtime DB role must not be able to bypass RLS (ADR-0014).

PostgreSQL ignores RLS policies for superusers and BYPASSRLS roles even under FORCE, so a
misconfigured connection user silently disables tenant isolation. This fails the build if the
role the application actually connects as can bypass RLS.

Reads GATEWAY_DATABASE__URL (the runtime URL). Exit 0 = safe, 1 = unsafe/unavailable.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_QUERY = (
    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
)


_BOOTSTRAP_HINT = """   The app_rw role has no LOGIN/password yet.

   Migration 0003 creates app_rw *without* a password on purpose (ADR-0011: secrets never
   live in migrations). LOGIN and the password come from the environment: in dev that is
   backend/docker/initdb/10-app-rw-role.sql, which Postgres only runs when the data volume
   is first created. An existing volume therefore has the role but no way to log in.

   Fix (non-destructive, run as the owner - single line, works in PowerShell and bash;
   run it from the PROJECT ROOT, where docker-compose.dev.yml lives):

     docker compose -f docker-compose.dev.yml exec postgres psql -U gateway -d gateway -c "ALTER ROLE app_rw WITH LOGIN PASSWORD 'app_rw';"

   Or re-provision from scratch (destroys dev data):
     docker compose -f docker-compose.dev.yml down -v
     docker compose -f docker-compose.dev.yml up -d"""


async def main() -> int:
    url = os.environ.get("GATEWAY_DATABASE__URL")
    if not url:
        print("   SKIP: GATEWAY_DATABASE__URL is not set")
        return 0
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rolname, rolsuper, rolbypassrls = (await conn.execute(text(_QUERY))).one()
    except Exception as exc:  # noqa: BLE001 - turn a stack trace into an actionable message
        message = str(exc)
        print(f"   FAIL: could not connect as the runtime role: {type(exc).__name__}")
        if (
            "password authentication failed" in message
            or "InvalidPassword" in type(exc).__name__
        ):
            print(_BOOTSTRAP_HINT)
        elif "does not exist" in message:
            print(
                "   The app_rw role does not exist. Run migrations as the owner first:"
            )
            print(
                "     alembic upgrade head   (with GATEWAY_DATABASE__URL = owner URL)"
            )
        else:
            print(f"   {message.splitlines()[0]}")
        return 1
    finally:
        await engine.dispose()
    print(f"   current_user={rolname} rolsuper={rolsuper} rolbypassrls={rolbypassrls}")
    if rolsuper or rolbypassrls:
        print("   FAIL: runtime role bypasses RLS - tenant isolation is NOT enforced.")
        return 1
    print("   PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
