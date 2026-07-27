"""Tests for the typed configuration system."""

from __future__ import annotations

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
