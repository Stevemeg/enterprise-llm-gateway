"""Tests for DatabaseSettings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gateway.config.settings import DatabaseSettings, Settings


def test_defaults() -> None:
    db = DatabaseSettings()
    assert db.pool_size == 20
    assert db.max_overflow == 10
    assert db.is_sqlite is False


def test_safe_url_masks_password() -> None:
    db = DatabaseSettings(url="postgresql+asyncpg://user:s3cret@host:5432/db")
    assert "s3cret" not in db.safe_url
    assert "***" in db.safe_url


def test_sqlite_is_detected() -> None:
    assert DatabaseSettings(url="sqlite+aiosqlite:///:memory:").is_sqlite is True


def test_nested_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_DATABASE__POOL_SIZE", "5")
    assert Settings().database.pool_size == 5


def test_pool_size_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        DatabaseSettings(pool_size=0)


def test_settings_are_immutable() -> None:
    db = DatabaseSettings()
    with pytest.raises(ValidationError):
        db.pool_size = 99  # type: ignore[misc]  # frozen
