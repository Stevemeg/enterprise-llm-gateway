"""Tests for the typed configuration system."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.config.settings import DeploymentMode, Environment, Settings, load_settings


def test_defaults_are_saas_and_json_logs() -> None:
    settings = Settings()
    assert settings.deployment_mode is DeploymentMode.SAAS
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.log_json is True


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_DEPLOYMENT_MODE", "self_hosted")
    monkeypatch.setenv("GATEWAY_ENVIRONMENT", "staging")
    settings = load_settings()
    assert settings.deployment_mode is DeploymentMode.SELF_HOSTED
    assert settings.environment is Environment.STAGING


def test_production_requires_json_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("GATEWAY_LOG_JSON", "false")
    with pytest.raises(ValidationError, match="Structured JSON logging is required"):
        load_settings()


def test_unknown_field_is_rejected() -> None:
    # extra="forbid" protects against typo'd fields when constructing settings in code.
    with pytest.raises(ValidationError):
        Settings(not_a_real_setting="x")  # type: ignore[call-arg]


def test_settings_are_immutable() -> None:
    settings = Settings()
    with pytest.raises(ValidationError):
        settings.app_name = "mutated"  # type: ignore[misc]  # frozen: assignment must fail


# --- Phase 5 M3: ingress protection ------------------------------------------------------------


def test_ingress_defaults_are_present_so_a_deployment_is_protected_without_configuration() -> None:
    """The limits must not be opt-in. A deployment that configures nothing still gets a bucket and
    a body cap - "protecting shared infra if no policy is set" (API_Rate_Limiting.md §2)."""
    ingress = Settings().ingress

    assert ingress.requests_per_second > 0
    assert ingress.burst >= 1
    assert ingress.max_request_bytes >= 1


def test_ingress_limits_are_operator_tunable_through_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAY_INGRESS__REQUESTS_PER_SECOND", "250")
    monkeypatch.setenv("GATEWAY_INGRESS__BURST", "500")
    monkeypatch.setenv("GATEWAY_INGRESS__MAX_REQUEST_BYTES", "4194304")

    ingress = load_settings().ingress

    assert ingress.requests_per_second == 250
    assert ingress.burst == 500
    assert ingress.max_request_bytes == 4_194_304


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("GATEWAY_INGRESS__REQUESTS_PER_SECOND", "0"),
        ("GATEWAY_INGRESS__BURST", "0"),
        ("GATEWAY_INGRESS__MAX_REQUEST_BYTES", "0"),
    ],
)
def test_a_limit_that_would_refuse_every_request_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    """Fail-fast rather than a deployment that starts and then denies all traffic. A protective
    control misconfigured into a total outage must be loud at boot, not discovered in production."""
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValidationError):
        load_settings()


# --- .env.example must remain valid application configuration -----------------------------------

#: The real, committed example file - not a fixture copy. Testing a recreation would have passed
#: while the actual file shipped broken, which is exactly how the original defect survived.
ENV_EXAMPLE = Path(__file__).parents[2] / ".env.example"


def _load_from(env_file: Path) -> Settings:
    """Load Settings from a dotenv file with the ambient GATEWAY_* environment removed.

    The isolation matters: pydantic-settings applies ``extra="forbid"`` to every key it reads
    *from the file*, while unknown OS environment variables are simply never collected. Leaving
    the shell's variables in place would let a passing OS env mask a broken file.
    """
    return Settings(_env_file=env_file)


@pytest.fixture
def _no_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [k for k in os.environ if k.startswith("GATEWAY_")]:
        monkeypatch.delenv(key, raising=False)


@pytest.mark.usefixtures("_no_gateway_env")
def test_the_committed_env_example_is_valid_application_configuration() -> None:
    """`cp backend/.env.example backend/.env` is the documented first setup step, so the file
    must load cleanly.

    It once did not: it carried an active ``GATEWAY_MIGRATION_DATABASE__URL`` line, which is a
    shell variable for the migration tooling and *not* a `Settings` field. Because `Settings`
    forbids unknown keys, copying the example made every `load_settings()` raise and the gateway
    could not start from a fresh clone. Nothing caught it, because no test ever loaded the file.
    """
    assert ENV_EXAMPLE.is_file(), f"missing {ENV_EXAMPLE}"

    settings = _load_from(ENV_EXAMPLE)

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.database.url.startswith("postgresql+asyncpg://")


@pytest.mark.usefixtures("_no_gateway_env")
def test_an_unknown_gateway_key_in_a_dotenv_file_is_rejected(tmp_path: Path) -> None:
    """Proves the test above can fail, and pins the strictness that makes it meaningful.

    This is the exact shape of the original defect: a `GATEWAY_*` key with no matching field.
    If this ever stops raising, `extra="forbid"` has been weakened and the guard above is vacuous.
    """
    broken = tmp_path / ".env.broken"
    broken.write_text(
        ENV_EXAMPLE.read_text(encoding="utf-8")
        + "\nGATEWAY_MIGRATION_DATABASE__URL=postgresql+asyncpg://o:o@localhost:5432/gateway\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="migration_database"):
        _load_from(broken)


@pytest.mark.usefixtures("_no_gateway_env")
def test_tooling_variables_are_commented_out_rather_than_active(tmp_path: Path) -> None:
    """`GATEWAY_MIGRATION_DATABASE__URL` and `GATEWAY_TEST_REDIS_URL` are consumed from the shell
    by the migration and validation tooling. They must stay documented but inactive, or they
    re-break the copy step."""
    active = {
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert "GATEWAY_MIGRATION_DATABASE__URL" not in active
    assert "GATEWAY_TEST_REDIS_URL" not in active
