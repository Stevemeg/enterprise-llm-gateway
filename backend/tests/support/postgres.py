"""Shared helpers for tests that require a real PostgreSQL instance (Gate 2 / CI).

Resolution order for the connection URL:
  1. ``GATEWAY_TEST_POSTGRES_URL`` — explicit override for test runners.
  2. ``GATEWAY_DATABASE__URL`` — the application's runtime URL, which per ADR-0014 is the
     least-privilege ``app_rw`` role. Using it here means the RLS/role tests validate the
     *exact* identity the app connects as, not a synthetic one.

Only a ``postgresql``/``postgres`` URL is accepted; a SQLite fallback returns ``None`` so
these tests skip (rather than run meaninglessly) when no Postgres is configured. Postgres
is present in Gate 2 and CI, so there these tests run and must pass (0 skipped).
"""

from __future__ import annotations

import os

import pytest


def postgres_test_url() -> str | None:
    """Return the Postgres URL for integration/security tests, or ``None`` to skip."""
    url = os.environ.get("GATEWAY_TEST_POSTGRES_URL") or os.environ.get("GATEWAY_DATABASE__URL")
    if url is None:
        return None
    backend = url.split("://", 1)[0].lower()
    if not backend.startswith("postgresql") and not backend.startswith("postgres"):
        return None
    return url


PG_URL: str | None = postgres_test_url()

requires_postgres = pytest.mark.skipif(
    PG_URL is None,
    reason="requires a migrated PostgreSQL reachable via GATEWAY_TEST_POSTGRES_URL or "
    "GATEWAY_DATABASE__URL (Gate 2 / CI); connection must be the app_rw runtime role (ADR-0014)",
)


def owner_test_url() -> str | None:
    """Return the OWNER/migrator Postgres URL (DDL-capable), or ``None`` to skip.

    Some tests must create/drop real objects (e.g. verifying ALTER DEFAULT PRIVILEGES),
    which the least-privilege ``app_rw`` runtime role cannot do. They connect as the owner
    via ``GATEWAY_MIGRATION_DATABASE__URL`` (see ADR-0014 / .env.example).
    """
    url = os.environ.get("GATEWAY_MIGRATION_DATABASE__URL")
    if url is None:
        return None
    backend = url.split("://", 1)[0].lower()
    if not backend.startswith("postgresql") and not backend.startswith("postgres"):
        return None
    return url


OWNER_URL: str | None = owner_test_url()

requires_postgres_owner = pytest.mark.skipif(
    OWNER_URL is None,
    reason="requires the owner/migrator URL (GATEWAY_MIGRATION_DATABASE__URL) to create test "
    "objects; app_rw cannot run DDL (ADR-0014)",
)
