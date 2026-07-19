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
