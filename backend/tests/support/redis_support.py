"""Shared helpers for tests that require a real Redis instance (Gate 2 / CI, Phase 5 M4).

Mirrors ``tests/support/postgres.py`` exactly, including its posture: a missing URL means these
tests **skip** rather than run meaninglessly, and Gate 2 configures the URL so there they run and
must pass with 0 skipped.

Resolution order:
  1. ``GATEWAY_TEST_REDIS_URL`` - explicit override for test runners.
  2. ``GATEWAY_REDIS__URL`` - the application's own runtime URL, so the tests exercise the exact
     endpoint the app connects to rather than a synthetic one.

Why a real Redis rather than a fake: ADR-0021's whole claim is that shared state works across
independent instances, and every property that could be wrong - script atomicity under concurrency,
server-side ``TIME``, ``EXPIRE`` semantics, key isolation - is a property of *Redis*, not of a
Python object pretending to be Redis. A fake would prove that two objects agree with a dict, which
is what the in-process limiter already does.
"""

from __future__ import annotations

import os

import pytest

_DEFAULT_TIMEOUT = 1.0


def redis_test_url() -> str | None:
    """Return the Redis URL for integration tests, or ``None`` to skip."""
    url = os.environ.get("GATEWAY_TEST_REDIS_URL") or os.environ.get("GATEWAY_REDIS__URL")
    if not url:
        return None
    if not url.split("://", 1)[0].lower().startswith("redis"):
        return None
    return url


REDIS_URL: str | None = redis_test_url()

requires_redis = pytest.mark.skipif(
    REDIS_URL is None,
    reason="requires a reachable Redis via GATEWAY_TEST_REDIS_URL or GATEWAY_REDIS__URL "
    "(Gate 2 / CI); ADR-0021 shared runtime state",
)
