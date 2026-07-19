"""Tests for the JWT-backed access-token service (issue + verify + rotation + failure)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.adapters.security.token_service import JwtTokenService
from gateway.domain.auth.errors import TokenInvalidError
from gateway.domain.auth.models import Principal, PrincipalType
from tests.conftest import FixedClock


def _service(provider: KeyProvider) -> JwtTokenService:
    jwt = JwtService(issuer="gw", audience="gateway", clock=FixedClock())
    return JwtTokenService(jwt, provider)


def _principal() -> Principal:
    return Principal(
        principal_type=PrincipalType.USER,
        subject_id=uuid4(),
        organization_id=uuid4(),
        scopes=("infer:chat",),
    )


def test_issue_and_verify_roundtrip() -> None:
    service = _service(KeyProvider.generate())
    principal = _principal()
    token = service.issue_access_token(principal=principal, ttl=timedelta(minutes=10))
    verified = service.verify(token)
    assert verified.subject_id == principal.subject_id
    assert verified.organization_id == principal.organization_id
    assert verified.principal_type is PrincipalType.USER
    assert verified.scopes == ("infer:chat",)


def test_token_verifies_after_key_rotation() -> None:
    provider = KeyProvider.generate("gateway-1")
    issuer = _service(provider)
    token = issuer.issue_access_token(principal=_principal(), ttl=timedelta(minutes=10))
    # rotate; a service using the rotated provider must still verify the old token
    verifier = _service(provider.rotate("gateway-2"))
    assert verifier.verify(token).principal_type is PrincipalType.USER


def test_token_from_unknown_key_is_rejected() -> None:
    issuer = _service(KeyProvider.generate("gateway-1"))
    token = issuer.issue_access_token(principal=_principal(), ttl=timedelta(minutes=10))
    stranger = _service(KeyProvider.generate("other"))  # unrelated keys
    with pytest.raises(TokenInvalidError):
        stranger.verify(token)


def test_garbage_token_is_rejected() -> None:
    service = _service(KeyProvider.generate())
    with pytest.raises(TokenInvalidError):
        service.verify("not-a-jwt")
