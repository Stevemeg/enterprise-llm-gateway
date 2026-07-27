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


@pytest.fixture(autouse=True)
def _isolate_tests_from_local_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop a developer's ``backend/.env`` from changing what the test suite means.

    ``docs/Local_Validation_Guide.md`` tells a developer to ``cp backend/.env.example
    backend/.env``. Doing so used to break four tests, because pydantic-settings applies that file
    to **every field the caller did not pass explicitly**:

    * ``test_defaults_are_saas_and_json_logs`` - bare ``Settings()`` picked up
      ``GATEWAY_LOG_JSON=false`` and stopped testing the code's default.
    * two ``test_shared_state_wiring`` tests - the helper passes ``database`` and ``auth`` but not
      ``redis``, so ``GATEWAY_REDIS__URL`` turned the deliberate *single-node* case into a
      *shared-state* one. Those tests exist precisely to prove the single-node wiring, so they did
      not merely fail - they silently changed meaning.
    * ``test_audit_event_is_emitted_as_structured_log`` - subtler and session-wide: an integration
      test builds ``Settings`` without ``log_json``, inherits ``false`` from the file, and
      ``Container.create`` calls ``configure_logging``, which is **global** structlog state. A
      later unit test then parsed a console-formatted line as JSON.

    That last path is why this fixture is suite-wide rather than scoped to ``tests/unit``.

    **Only the dotenv file is disabled. Nothing else changes:**

    * *OS environment variables still apply*, so tests that deliberately exercise them
      (``test_env_overrides``, ``test_production_requires_json_logging``, the ingress-tunability
      and pool-size tests) keep working - this fixture runs first, then the test sets what it needs.
    * *Explicit* ``_env_file=`` *still wins*, so the ``.env.example`` regressions in
      ``test_settings.py`` keep exercising real dotenv loading.
    * *Integration and security configuration is untouched*: ``tests/support/postgres.py`` and
      ``tests/support/redis_support.py`` read ``os.environ`` directly, and the validation scripts
      inject ``GATEWAY_*`` the same way.

    This is stabilising rather than restricting: ``.env`` is gitignored, so it never exists in CI
    or a fresh clone. The suite already had to pass without it; this makes that the guaranteed
    state instead of an accident of whether a developer ran the setup guide.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)


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
