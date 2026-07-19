"""Integration tests for the authentication middleware (via a test app)."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from gateway.adapters.audit.logging_sink import LoggingAuthAuditSink
from gateway.adapters.security.api_keys import generate_api_key
from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.adapters.security.token_service import JwtTokenService
from gateway.application.auth.authenticate_api_key import AuthenticateApiKey
from gateway.application.auth.authenticate_request import CompositeAuthenticator
from gateway.delivery.http.middleware.authentication import AuthenticationMiddleware
from gateway.delivery.http.middleware.request_context import RequestContextMiddleware
from gateway.domain.auth.models import (
    ApiKeyRecord,
    AuthenticationContext,
    AuthenticationMethod,
    Principal,
    PrincipalType,
)
from tests.conftest import FixedClock
from tests.support.auth_fakes import InMemoryApiKeyRepository


def _build(app_keys: InMemoryApiKeyRepository, tokens: JwtTokenService) -> TestClient:
    api_key_uc = AuthenticateApiKey(app_keys, FixedClock())
    authenticator = CompositeAuthenticator(api_key_uc, tokens)
    app = FastAPI()
    # request-context added last => outermost => binds request_id before auth runs
    app.add_middleware(
        AuthenticationMiddleware, authenticator=authenticator, audit=LoggingAuthAuditSink()
    )
    app.add_middleware(RequestContextMiddleware)

    @app.get("/protected")
    async def protected(request: Request) -> dict[str, str]:
        # Downstream reads exactly one object: the AuthenticationContext.
        auth: AuthenticationContext = request.state.auth
        return {
            "subject": str(auth.principal_id),
            "type": auth.principal_type.value,
            "method": auth.authentication_method.value,
            "organization": str(auth.organization_id),
        }

    @app.get("/public")
    async def public() -> dict[str, str]:
        return {"ok": "yes"}

    return TestClient(app)


def _tokens() -> JwtTokenService:
    return JwtTokenService(
        JwtService(issuer="gw", audience="gateway", clock=FixedClock()), KeyProvider.generate()
    )


def test_public_route_without_credential_passes() -> None:
    client = _build(InMemoryApiKeyRepository(), _tokens())
    assert client.get("/public").status_code == 200


def test_valid_jwt_attaches_principal() -> None:
    tokens = _tokens()
    principal = Principal(PrincipalType.USER, uuid4(), uuid4())
    token = tokens.issue_access_token(principal=principal, ttl=timedelta(minutes=10))
    client = _build(InMemoryApiKeyRepository(), tokens)
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["type"] == "user"


def test_valid_api_key_attaches_principal() -> None:
    repo = InMemoryApiKeyRepository()
    key = generate_api_key()
    repo.store(
        key.prefix,
        ApiKeyRecord(
            id=uuid4(),
            organization_id=uuid4(),
            key_hash=key.key_hash,
            scopes=("infer:chat",),
            is_active=True,
        ),
    )
    client = _build(repo, _tokens())
    response = client.get("/protected", headers={"Authorization": f"Bearer {key.secret}"})
    assert response.status_code == 200
    assert response.json()["type"] == "api_key"


def test_invalid_token_is_rejected_401() -> None:
    client = _build(InMemoryApiKeyRepository(), _tokens())
    response = client.get("/protected", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"


def test_malformed_header_is_rejected_401() -> None:
    client = _build(InMemoryApiKeyRepository(), _tokens())
    response = client.get("/protected", headers={"Authorization": "Token abc"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_authorization_header"


def test_unknown_api_key_is_rejected_401() -> None:
    client = _build(InMemoryApiKeyRepository(), _tokens())
    response = client.get("/protected", headers={"Authorization": "Bearer elg_live_unknown"})
    assert response.status_code == 401


def test_authenticated_request_exposes_a_single_typed_context() -> None:
    """The middleware must attach exactly one object — no attribute sprawl on request.state."""
    keys = InMemoryApiKeyRepository()
    tokens = _tokens()
    org, user = uuid4(), uuid4()
    token = tokens.issue_access_token(
        principal=Principal(PrincipalType.USER, user, org), ttl=timedelta(minutes=5)
    )
    client = _build(keys, tokens)

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == str(user)
    assert body["organization"] == str(org)
    assert body["method"] == AuthenticationMethod.JWT.value


def test_authentication_context_is_immutable() -> None:
    """Downstream code must not be able to mutate the authenticated identity."""
    context = AuthenticationContext(
        principal_id=uuid4(),
        principal_type=PrincipalType.USER,
        organization_id=uuid4(),
        authentication_method=AuthenticationMethod.JWT,
        scopes=("infer:chat",),
    )

    with pytest.raises((AttributeError, TypeError)):
        context.organization_id = uuid4()  # type: ignore[misc]

    assert context.has_scope("infer:chat")
    assert not context.has_scope("admin:write")
