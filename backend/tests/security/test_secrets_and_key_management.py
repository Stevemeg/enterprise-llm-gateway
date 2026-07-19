"""Key-management remediation: AUTH-01, AUTH-02, AUTH-04 (Authentication Security Review).

Three properties are asserted here:
  1. A secret *reference* is never used as key material (AUTH-02).
  2. Production refuses to boot on generated/placeholder keys or an unavailable secrets
     manager; development may opt into a documented fallback (AUTH-01, review requirement).
  3. Key rotation keeps previous keys verifying during the overlap window (AUTH-01/Q7).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from gateway.adapters.secrets.env_resolver import (
    EnvSecretsResolver,
    InMemorySecretsResolver,
    reference_to_env_var,
)
from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.adapters.security.keys import generate_signing_key
from gateway.adapters.security.token_service import JwtTokenService
from gateway.application.ports.secrets import SecretNotFoundError
from gateway.config.container import Container
from gateway.config.settings import (
    AuthSettings,
    DatabaseSettings,
    DeploymentMode,
    Environment,
    Settings,
)
from gateway.domain.auth.errors import AuthError
from gateway.domain.auth.models import Principal, PrincipalType
from tests.conftest import FixedClock

_JWT_REF = "gateway/jwt/signing-key"
_STATE_REF = "gateway/oidc/state-signing-key"


def _settings(*, environment: Environment, allow_generated: bool) -> Settings:
    return Settings(
        environment=environment,
        deployment_mode=DeploymentMode.SAAS,
        log_json=True,
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        auth=AuthSettings(allow_insecure_generated_keys=allow_generated),
    )


def _resolver_with_keys() -> InMemorySecretsResolver:
    return InMemorySecretsResolver(
        {
            _JWT_REF: generate_signing_key("gateway-1").private_pem,
            _STATE_REF: "a-real-state-signing-secret",
        }
    )


# --- AUTH-02: references are not key material -------------------------------------------------


def test_reference_maps_to_env_var_and_is_not_itself_a_secret() -> None:
    assert reference_to_env_var(_STATE_REF) == "GATEWAY_SECRET_GATEWAY__OIDC__STATE_SIGNING_KEY"
    # The raw reference resolves to nothing on its own — it is a pointer, not material.
    assert EnvSecretsResolver({}).try_resolve(_STATE_REF) is None


def test_state_signer_never_receives_the_reference_string() -> None:
    container = Container.create(
        _settings(environment=Environment.DEVELOPMENT, allow_generated=False),
        secrets_resolver=_resolver_with_keys(),
    )
    # The signer must hold resolved material, never the pointer (AUTH-02).
    assert container.state_signer._key == "a-real-state-signing-secret"
    assert container.state_signer._key != _STATE_REF


def test_missing_secret_raises_rather_than_falling_back_silently() -> None:
    with pytest.raises(SecretNotFoundError, match="could not be resolved"):
        Container.create(
            _settings(environment=Environment.DEVELOPMENT, allow_generated=False),
            secrets_resolver=InMemorySecretsResolver({}),
        )


# --- AUTH-01: production must not boot on generated keys --------------------------------------


def test_production_rejects_generated_keys_in_configuration() -> None:
    with pytest.raises(ValueError, match="ALLOW_INSECURE_GENERATED_KEYS"):
        _settings(environment=Environment.PRODUCTION, allow_generated=True)


def test_production_startup_fails_when_secrets_manager_unavailable() -> None:
    """A production instance must never boot with placeholder or ephemeral keys."""
    with pytest.raises(SecretNotFoundError):
        Container.create(
            _settings(environment=Environment.PRODUCTION, allow_generated=False),
            secrets_resolver=InMemorySecretsResolver({}),  # secrets manager "down"
        )


def test_development_may_use_the_documented_fallback() -> None:
    container = Container.create(
        _settings(environment=Environment.DEVELOPMENT, allow_generated=True),
        secrets_resolver=InMemorySecretsResolver({}),
    )
    assert container.key_provider.current.private_pem  # generated, dev only
    assert container.state_signer is not None


def test_managed_key_is_used_when_available() -> None:
    resolver = _resolver_with_keys()
    container = Container.create(
        _settings(environment=Environment.DEVELOPMENT, allow_generated=True),
        secrets_resolver=resolver,
    )
    assert container.key_provider.current.private_pem == resolver.resolve(_JWT_REF)


# --- AUTH-01 / Q7: rotation overlap must not lock users out -----------------------------------


def _token_service(provider: KeyProvider) -> JwtTokenService:
    return JwtTokenService(
        JwtService(issuer="gw", audience="gateway", clock=FixedClock()), provider
    )


def test_rotation_keeps_previous_key_verifying_during_overlap() -> None:
    """A token signed before rotation must still verify after it — else rotation = mass logout."""
    old = KeyProvider.from_pem(
        kid="old-kid", private_pem=generate_signing_key("old-kid").private_pem
    )
    principal = Principal(PrincipalType.USER, uuid4(), uuid4())
    token_from_old_key = _token_service(old).issue_access_token(
        principal=principal, ttl=timedelta(minutes=10)
    )

    rotated = old.rotate("new-kid")  # retains the old public key

    verified = _token_service(rotated).verify(token_from_old_key)
    assert verified.subject_id == principal.subject_id
    assert "old-kid" in rotated.verification_keys()
    assert "new-kid" in rotated.verification_keys()
    assert set(rotated.jwks()["keys"][0].keys()) >= {"kid", "kty"}


def test_token_from_retired_key_is_rejected_once_overlap_closes() -> None:
    old = KeyProvider.from_pem(
        kid="old-kid", private_pem=generate_signing_key("old-kid").private_pem
    )
    token_from_old_key = _token_service(old).issue_access_token(
        principal=Principal(PrincipalType.USER, uuid4(), uuid4()), ttl=timedelta(minutes=10)
    )
    # Rotation completed and the overlap window has closed: only the new key remains.
    closed = KeyProvider.from_pem(
        kid="new-kid", private_pem=generate_signing_key("new-kid").private_pem
    )

    with pytest.raises(AuthError):
        _token_service(closed).verify(token_from_old_key)


def test_previous_key_that_cannot_be_resolved_fails_startup() -> None:
    """Silently dropping a retired key would shrink the rotation window without warning."""
    settings = Settings(
        environment=Environment.DEVELOPMENT,
        deployment_mode=DeploymentMode.SAAS,
        log_json=True,
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        auth=AuthSettings(jwt_previous_key_refs=("old-kid=gateway/jwt/retired-key",)),
    )
    with pytest.raises(SecretNotFoundError, match="previous signing key"):
        Container.create(settings, secrets_resolver=_resolver_with_keys())
