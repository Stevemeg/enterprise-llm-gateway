"""Shared test fixtures and helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gateway.config.settings import (
    AuthSettings,
    DatabaseSettings,
    DeploymentMode,
    Environment,
    Settings,
)


class FixedClock:
    """Deterministic clock for tests (satisfies the ``Clock`` protocol)."""

    def __init__(self, moment: datetime | None = None) -> None:
        self._moment = moment or datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._moment


@pytest.fixture
def test_settings() -> Settings:
    """Deterministic settings independent of the host environment (SQLite DB)."""
    return Settings(
        environment=Environment.DEVELOPMENT,
        deployment_mode=DeploymentMode.SAAS,
        log_json=True,
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        # No secrets manager in tests: opt in explicitly to generated keys. This is the
        # dev-only path the settings validator forbids in production (ADR-0011 / AUTH-01).
        auth=AuthSettings(allow_insecure_generated_keys=True),
    )
