"""Tests for service-account (client-credentials) authentication (ADR-0013)."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from gateway.application.auth.authenticate_service_account import AuthenticateServiceAccount
from gateway.domain.auth.errors import CredentialInvalidError
from gateway.domain.auth.models import ServiceAccountCredentialRecord
from gateway.shared.secrets import hash_secret
from tests.conftest import FixedClock
from tests.support.auth_fakes import (
    FakeTokenService,
    InMemoryServiceAccountCredentialRepository,
)

_TTL = timedelta(minutes=5)


def _store(
    repo: InMemoryServiceAccountCredentialRepository,
    secret: str,
    *,
    status: str = "active",
    expires_at: datetime | None = None,
) -> None:
    repo.store(
        ServiceAccountCredentialRecord(
            id=uuid4(),
            service_account_id=uuid4(),
            organization_id=uuid4(),
            client_id="client-1",
            secret_hash=hash_secret(secret),
            status=status,
            expires_at=expires_at,
        )
    )


def _uc(
    repo: InMemoryServiceAccountCredentialRepository, clock: FixedClock
) -> AuthenticateServiceAccount:
    return AuthenticateServiceAccount(repo, FakeTokenService(), clock, access_ttl=_TTL)


async def test_valid_credentials_issue_token() -> None:
    repo = InMemoryServiceAccountCredentialRepository()
    _store(repo, "s3cret")
    token = await _uc(repo, FixedClock())("client-1", "s3cret")
    assert token.startswith("access.service_account.")


async def test_unknown_client_is_rejected() -> None:
    repo = InMemoryServiceAccountCredentialRepository()
    with pytest.raises(CredentialInvalidError):
        await _uc(repo, FixedClock())("nope", "x")


async def test_wrong_secret_is_rejected() -> None:
    repo = InMemoryServiceAccountCredentialRepository()
    _store(repo, "s3cret")
    with pytest.raises(CredentialInvalidError):
        await _uc(repo, FixedClock())("client-1", "wrong")


async def test_revoked_credential_is_rejected() -> None:
    repo = InMemoryServiceAccountCredentialRepository()
    _store(repo, "s3cret", status="revoked")
    with pytest.raises(CredentialInvalidError):
        await _uc(repo, FixedClock())("client-1", "s3cret")


async def test_expired_credential_is_rejected() -> None:
    repo = InMemoryServiceAccountCredentialRepository()
    clock = FixedClock()
    _store(repo, "s3cret", expires_at=clock.now() - timedelta(seconds=1))
    with pytest.raises(CredentialInvalidError):
        await _uc(repo, clock)("client-1", "s3cret")
