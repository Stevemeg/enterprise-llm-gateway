"""Tests for API-key authentication (success + failure modes)."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from gateway.adapters.security.api_keys import GeneratedApiKey, generate_api_key
from gateway.application.auth.authenticate_api_key import AuthenticateApiKey
from gateway.domain.auth.errors import CredentialInvalidError
from gateway.domain.auth.models import ApiKeyRecord, PrincipalType
from tests.conftest import FixedClock
from tests.support.auth_fakes import InMemoryApiKeyRepository


def _store_key(
    repo: InMemoryApiKeyRepository,
    *,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> GeneratedApiKey:
    key = generate_api_key()
    org = uuid4()
    repo.store(
        key.prefix,
        ApiKeyRecord(
            id=uuid4(),
            organization_id=org,
            key_hash=key.key_hash,
            scopes=("infer:chat",),
            is_active=is_active,
            expires_at=expires_at,
        ),
    )
    return key


async def test_valid_key_authenticates() -> None:
    repo = InMemoryApiKeyRepository()
    key = _store_key(repo)
    principal = await AuthenticateApiKey(repo, FixedClock())(key.secret)
    assert principal.principal_type is PrincipalType.API_KEY
    assert principal.scopes == ("infer:chat",)


async def test_unknown_key_is_rejected() -> None:
    repo = InMemoryApiKeyRepository()
    with pytest.raises(CredentialInvalidError):
        await AuthenticateApiKey(repo, FixedClock())("elg_live_does_not_exist")


async def test_wrong_secret_is_rejected() -> None:
    repo = InMemoryApiKeyRepository()
    key = _store_key(repo)
    with pytest.raises(CredentialInvalidError):
        await AuthenticateApiKey(repo, FixedClock())(key.secret + "tamper")


async def test_inactive_key_is_rejected() -> None:
    repo = InMemoryApiKeyRepository()
    key = _store_key(repo, is_active=False)
    with pytest.raises(CredentialInvalidError):
        await AuthenticateApiKey(repo, FixedClock())(key.secret)


async def test_expired_key_is_rejected() -> None:
    repo = InMemoryApiKeyRepository()
    clock = FixedClock()
    key = _store_key(repo, expires_at=clock.now() - timedelta(seconds=1))
    with pytest.raises(CredentialInvalidError):
        await AuthenticateApiKey(repo, clock)(key.secret)
