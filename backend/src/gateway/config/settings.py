"""Typed application settings (Backend_Implementation_Guide.md §10).

Settings are loaded from environment variables (prefix ``GATEWAY_``, nested via ``__``)
and an optional ``.env`` file, validated on construction, and **immutable** for the
process lifetime. Invalid configuration raises immediately — fail-fast at startup
(FR-146, ADR-0009 row 16). Secret *values* are never settings; only references are
(ADR-0011). Any password in the database URL is masked in ``safe_url``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class DeploymentMode(StrEnum):
    """One codebase, two deployment modes (NFR-D01, ADR-0011)."""

    SAAS = "saas"
    SELF_HOSTED = "self_hosted"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DatabaseSettings(BaseModel):
    """PostgreSQL connection + pool configuration (ADR-0002, Query_Performance_Guide §12).

    Defaults target a local Postgres; production overrides via ``GATEWAY_DATABASE__*``.
    SQLite (async) is supported for local/testing only.
    """

    model_config = {"frozen": True}

    url: str = "postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"
    pool_size: int = Field(default=20, ge=1)
    max_overflow: int = Field(default=10, ge=0)
    pool_timeout_seconds: float = Field(default=30.0, gt=0)
    pool_recycle_seconds: int = Field(default=1800, ge=0)
    echo: bool = False

    @property
    def safe_url(self) -> str:
        """URL with any password redacted — safe to log (NFR-SEC03)."""
        return make_url(self.url).render_as_string(hide_password=True)

    @property
    def is_sqlite(self) -> bool:
        return make_url(self.url).get_backend_name() == "sqlite"


class OidcSettings(BaseModel):
    """OIDC identity-provider configuration (ADR-0015). Disabled unless ``issuer`` is set.

    The client secret is a **reference**, never an inline value (ADR-0011): it names an entry
    in the secrets manager, resolved at startup.
    """

    model_config = {"frozen": True}

    issuer: str = ""
    client_id: str = ""
    client_secret_ref: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    jwks_uri: str = ""
    redirect_uri: str = ""
    jwks_ttl_seconds: int = Field(default=600, gt=0)  # 10 minutes (ADR-0015)

    @property
    def is_configured(self) -> bool:
        return bool(self.issuer and self.client_id and self.token_endpoint and self.jwks_uri)


class AuthSettings(BaseModel):
    """Authentication configuration (ADR-0008/0015)."""

    model_config = {"frozen": True}

    jwt_issuer: str = "enterprise-llm-gateway"
    jwt_audience: str = "gateway"
    access_token_ttl_seconds: int = Field(default=900, gt=0)  # 15 min
    session_ttl_seconds: int = Field(default=604800, gt=0)  # 7 days
    oidc_state_ttl_seconds: int = Field(default=300, gt=0)  # 5 min (ADR-0015)
    clock_skew_leeway_seconds: int = Field(default=60, ge=0)
    # References to secrets (ADR-0011). These are POINTERS resolved via SecretsResolver at
    # startup — never key material. Using a reference as a key was security finding AUTH-02.
    state_signing_key_ref: str = "gateway/oidc/state-signing-key"
    jwt_signing_key_ref: str = "gateway/jwt/signing-key"
    jwt_signing_kid: str = "gateway-1"
    # Retired keys still inside the rotation overlap window: "kid=reference" pairs. Tokens they
    # signed keep verifying until removed, so rotation never locks users out (AUTH-01).
    jwt_previous_key_refs: tuple[str, ...] = ()
    # Development escape hatch: generate ephemeral keys when secrets cannot be resolved.
    # Ignored in production, where startup fails instead (see the validator below).
    allow_insecure_generated_keys: bool = False
    oidc: OidcSettings = OidcSettings()


class ProviderConnectionSettings(BaseModel):
    """How to reach one provider (ADR-0003/0011, Slice 19).

    Deployment configuration, keyed in ``Settings.providers`` by the provider's catalog name, e.g.
    ``GATEWAY_PROVIDERS__OPENAI__BASE_URL``. It is deliberately separate from the tenant-scoped
    ``provider`` table the catalog reads: the catalog decides *which* providers an organization may
    route to, this decides *how the deployment reaches* one, and only the ``ProviderClient`` adapter
    ever sees both. Putting an endpoint or a credential on ``ProviderDescriptor`` would push them
    through ``RoutingExecution`` and into the routing record.

    ``api_key_ref`` is a **reference**, never an inline value (ADR-0011): it names an entry in the
    secrets manager, resolved once at startup. A missing reference fails startup rather than
    producing a client that 401s against every provider (ADR-0009 row 16).

    Per-tenant endpoints and BYO credentials are a real future capability with no consumer today
    and no per-tenant secret storage to resolve them against, so they are deferred, not modelled.
    """

    model_config = {"frozen": True}

    base_url: str = ""
    api_key_ref: str = ""
    # Explicit, never httpx's own default: a hung provider must fail as a retryable TIMEOUT rather
    # than occupy the request path indefinitely.
    timeout_seconds: float = Field(default=30.0, gt=0)


class Settings(BaseSettings):
    """Immutable, validated process configuration."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    app_name: str = "enterprise-llm-gateway"
    service_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    deployment_mode: DeploymentMode = DeploymentMode.SAAS
    log_level: LogLevel = LogLevel.INFO
    log_json: bool = True
    database: DatabaseSettings = DatabaseSettings()
    auth: AuthSettings = AuthSettings()
    providers: dict[str, ProviderConnectionSettings] = {}
    # Phase 5 M2. With no provider connections configured, the gateway refuses provider calls
    # (UnconfiguredProviderClient) rather than echoing the prompt back as a successful inference
    # and booking spend for it. Local development and the integration suite opt back into the
    # synthesizing in-memory client explicitly, which is what makes it visible; production may
    # not, and the validator below enforces that the same way it does for generated signing keys.
    allow_fake_provider_client: bool = False
    # Phase 5 M2. How long a budget hold may legitimately stay reserved before reconciliation
    # reclaims it. An UPPER BOUND on request duration, not a cleanup interval: setting it below
    # the longest real request would reclaim live holds and let a tenant overspend. Default 15
    # minutes, far beyond the 30s provider timeout x 3 reflection attempts this gateway can
    # currently produce (see application/accounting/reservation_reconciler.py).
    reservation_ttl_seconds: int = Field(default=900, gt=0)

    @model_validator(mode="after")
    def _enforce_production_invariants(self) -> Settings:
        # Structured logging is mandatory in production for observability + PII-safe
        # log shipping (FR-082). Human-readable console logs are dev-only.
        if self.environment is Environment.PRODUCTION and not self.log_json:
            raise ValueError(
                "Structured JSON logging is required in production (set GATEWAY_LOG_JSON=true)."
            )
        # Fail fast rather than silently signing with placeholder or ephemeral keys.
        if self.environment is Environment.PRODUCTION:
            if not self.auth.state_signing_key_ref:
                raise ValueError(
                    "GATEWAY_AUTH__STATE_SIGNING_KEY_REF must be set in production (ADR-0011/0015)."
                )
            if not self.auth.jwt_signing_key_ref:
                raise ValueError(
                    "GATEWAY_AUTH__JWT_SIGNING_KEY_REF must be set in production (ADR-0011)."
                )
            if self.auth.allow_insecure_generated_keys:
                raise ValueError(
                    "GATEWAY_AUTH__ALLOW_INSECURE_GENERATED_KEYS must be false in production: "
                    "generated per-process keys invalidate tokens on restart and break replicas "
                    "(AUTH-01)."
                )
            if self.allow_fake_provider_client:
                raise ValueError(
                    "GATEWAY_ALLOW_FAKE_PROVIDER_CLIENT must be false in production: the "
                    "in-memory client fabricates a successful response and synthesizes usage, so "
                    "a production deployment would serve invented answers and book real spend "
                    "for inferences that never happened."
                )
        return self


def load_settings() -> Settings:
    """Load and validate settings, raising on invalid configuration (fail-fast)."""
    return Settings()
