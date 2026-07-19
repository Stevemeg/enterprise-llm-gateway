"""Dependency-injection container — the composition root (Guide §9).

The single place concrete implementations are constructed and bound. Chosen by
``Settings`` (profile/backends). Constructed once at startup and passed down via
constructor injection; business code never reaches back into the container.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.audit.composite_sink import CompositeAuthAuditSink
from gateway.adapters.audit.logging_sink import LoggingAuthAuditSink
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.health import DatabaseHealthCheck
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.adapters.secrets.env_resolver import EnvSecretsResolver
from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.adapters.security.keys import derive_public_pem
from gateway.adapters.security.oidc_state import StateSigner
from gateway.adapters.security.token_service import JwtTokenService
from gateway.application.ports.auth import AuthAuditSink
from gateway.application.ports.secrets import SecretNotFoundError, SecretsResolver
from gateway.config.settings import AuthSettings, Settings
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.observability.logging import configure_logging, get_logger
from gateway.shared.clock import Clock, SystemClock
from gateway.shared.secrets import generate_token


def _build_key_provider(auth: AuthSettings, secrets: SecretsResolver) -> KeyProvider:
    """Load the JWT signing key from the secrets manager, with previous keys for rotation.

    Production must supply managed material: per-process generation invalidates every token on
    restart and makes replicas disagree on JWKS (AUTH-01). Development may opt into generation
    explicitly via ``allow_insecure_generated_keys``.
    """
    private_pem = secrets.try_resolve(auth.jwt_signing_key_ref)
    if private_pem is None:
        if not auth.allow_insecure_generated_keys:
            raise SecretNotFoundError(
                f"JWT signing key {auth.jwt_signing_key_ref!r} could not be resolved. "
                "Provide it via the secrets manager, or set "
                "GATEWAY_AUTH__ALLOW_INSECURE_GENERATED_KEYS=true for local development only."
            )
        get_logger("bootstrap").warning(
            "insecure_generated_signing_key",
            reason="secret unresolved; generating an ephemeral key (DEV ONLY)",
            reference=auth.jwt_signing_key_ref,
        )
        return KeyProvider.generate(auth.jwt_signing_kid)

    previous: list[tuple[str, str]] = []
    for entry in auth.jwt_previous_key_refs:
        kid, _, reference = entry.partition("=")
        material = secrets.try_resolve(reference) if reference else None
        if material is None:
            # A retired key we cannot load would silently shrink the rotation window.
            raise SecretNotFoundError(
                f"previous signing key {entry!r} could not be resolved; "
                "tokens signed by it would stop verifying mid-rotation (AUTH-01)."
            )
        previous.append((kid, derive_public_pem(material)))

    return KeyProvider.from_pem(
        kid=auth.jwt_signing_kid,
        private_pem=private_pem,
        previous=tuple(previous),
    )


def _resolve_state_signing_key(auth: AuthSettings, secrets: SecretsResolver) -> str:
    """Resolve the OIDC state HMAC key. A *reference* must never be used as key material."""
    material = secrets.try_resolve(auth.state_signing_key_ref)
    if material is not None:
        return material
    if not auth.allow_insecure_generated_keys:
        raise SecretNotFoundError(
            f"OIDC state signing key {auth.state_signing_key_ref!r} could not be resolved. "
            "Provide it via the secrets manager, or set "
            "GATEWAY_AUTH__ALLOW_INSECURE_GENERATED_KEYS=true for local development only."
        )
    get_logger("bootstrap").warning(
        "insecure_generated_state_key",
        reason="secret unresolved; generating an ephemeral key (DEV ONLY, single-instance)",
        reference=auth.state_signing_key_ref,
    )
    return generate_token()


@dataclass(frozen=True, slots=True)
class Container:
    """Holds the wired singletons for a process."""

    settings: Settings
    clock: Clock
    engine: AsyncEngine
    uow_factory: UnitOfWorkFactory
    health: HealthRegistry
    key_provider: KeyProvider
    token_service: JwtTokenService
    audit_sink: AuthAuditSink
    state_signer: StateSigner

    @classmethod
    def create(
        cls, settings: Settings, *, secrets_resolver: SecretsResolver | None = None
    ) -> Container:
        """Assemble the object graph. ``secrets_resolver`` is injectable for tests."""
        configure_logging(level=settings.log_level.value, json_output=settings.log_json)
        clock: Clock = SystemClock()

        db = settings.database
        engine = create_database_engine(
            url=db.url,
            echo=db.echo,
            pool_size=db.pool_size,
            max_overflow=db.max_overflow,
            pool_timeout_seconds=db.pool_timeout_seconds,
            pool_recycle_seconds=db.pool_recycle_seconds,
        )
        session_factory = create_session_factory(engine)
        rls_enabled = engine.dialect.name == "postgresql"
        uow_factory = UnitOfWorkFactory(session_factory, rls_enabled=rls_enabled)

        # --- authentication object graph (ADR-0008/0014/0015) ---------------------------
        auth = settings.auth
        secrets: SecretsResolver = secrets_resolver or EnvSecretsResolver()
        key_provider = _build_key_provider(auth, secrets)
        jwt_service = JwtService(issuer=auth.jwt_issuer, audience=auth.jwt_audience, clock=clock)
        token_service = JwtTokenService(jwt_service, key_provider)
        # Composite so the durable hash-chained audit_event sink drops in later (ADR-0009)
        # without changing any call site.
        audit_sink: AuthAuditSink = CompositeAuthAuditSink([LoggingAuthAuditSink()])
        # Signs the tenant hint inside the OIDC ``state`` so the callback can resolve the org
        # before any DB access. Resolved from the secrets manager in production (ADR-0011);
        # a per-process ephemeral key is used only when no reference is configured, which
        # confines any such deployment to a single instance by construction.
        state_signer = StateSigner(_resolve_state_signing_key(auth, secrets))

        health = HealthRegistry(version=settings.service_version, clock=clock)
        health.register("database", DatabaseHealthCheck(engine))

        get_logger("bootstrap").info(
            "container_initialised",
            environment=settings.environment.value,
            deployment_mode=settings.deployment_mode.value,
            service_version=settings.service_version,
            database=db.safe_url,
            rls_enabled=rls_enabled,
            oidc_configured=auth.oidc.is_configured,
            signing_kid=key_provider.current.kid,
        )
        return cls(
            settings=settings,
            clock=clock,
            engine=engine,
            uow_factory=uow_factory,
            health=health,
            key_provider=key_provider,
            token_service=token_service,
            audit_sink=audit_sink,
            state_signer=state_signer,
        )

    async def dispose(self) -> None:
        """Release owned resources (connection pool). Called on app shutdown."""
        await self.engine.dispose()
