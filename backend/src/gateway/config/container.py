"""Dependency-injection container — the composition root (Guide §9).

The single place concrete implementations are constructed and bound. Chosen by
``Settings`` (profile/backends). Constructed once at startup and passed down via
constructor injection; business code never reaches back into the container.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.audit.composite_sink import CompositeAuthAuditSink
from gateway.adapters.audit.logging_sink import LoggingAuthAuditSink
from gateway.adapters.audit.sql_sink import SqlAuthAuditSink
from gateway.adapters.authorization.null_resolver import NullPermissionResolver
from gateway.adapters.authorization.sql_resolver import SqlPermissionResolver
from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.cache.sql_response_cache import SqlResponseCache
from gateway.adapters.catalog.sql_provider_catalog import SqlProviderCatalog
from gateway.adapters.health.in_memory_circuit_breaker import InMemoryCircuitBreaker
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.ledger.sql_budget_ledger import SqlBudgetLedger
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.health import DatabaseHealthCheck
from gateway.adapters.persistence.repositories.auth_repositories import (
    TenantScopedApiKeyRepository,
)
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.adapters.pipeline.authorization_stage import AuthorizationStage
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.adapters.pricing.sql_price_table import SqlPriceTable
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.in_memory_client import InMemoryProviderClient
from gateway.adapters.providers.openai_compatible_client import (
    OpenAiCompatibleProviderClient,
    ProviderConnection,
)
from gateway.adapters.providers.unconfigured_client import UnconfiguredProviderClient
from gateway.adapters.secrets.env_resolver import EnvSecretsResolver
from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.adapters.security.keys import derive_public_pem
from gateway.adapters.security.oidc_state import StateSigner
from gateway.adapters.security.token_authenticator import BearerTokenAuthenticator
from gateway.adapters.security.token_service import JwtTokenService
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_reconciler import ReservationReconciler
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.auth.authenticate_api_key import AuthenticateApiKey
from gateway.application.auth.authenticate_request import CompositeAuthenticator
from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.runner import EvaluationRunner
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.pipeline.runner import RequestPipeline
from gateway.application.ports.auth import AuthAuditSink, Authenticator
from gateway.application.ports.authorization import PermissionResolver
from gateway.application.ports.cache import ResponseCachePort
from gateway.application.ports.circuit_breaker import CircuitBreaker
from gateway.application.ports.evaluation import Evaluator
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.policy import PolicyEnginePort
from gateway.application.ports.pricing import PricingPort
from gateway.application.ports.providers import ProviderClient
from gateway.application.ports.routing import RoutingEngine
from gateway.application.ports.routing_strategy import RoutingStrategy
from gateway.application.ports.secrets import SecretNotFoundError, SecretsResolver
from gateway.application.ports.streaming import StreamingProviderClient
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.providers.streaming_executor import StreamingProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.routing.catalog import InMemoryProviderCatalog, ProviderCatalog
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
from gateway.application.routing.health_tiered_strategy import HealthTieredRoutingStrategy
from gateway.application.serving.inference_service import InferenceService
from gateway.application.streaming.streaming_coordinator import StreamingCoordinator
from gateway.config.settings import AuthSettings, Settings
from gateway.delivery.http.ops.health import HealthRegistry
from gateway.observability.logging import configure_logging, get_logger
from gateway.shared.clock import AsyncioSleeper, Clock, Sleeper, SystemClock
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


def _build_provider_connections(
    settings: Settings, secrets: SecretsResolver
) -> dict[str, ProviderConnection]:
    """Resolve each configured provider's credential into a usable connection (ADR-0003/0011).

    A configured provider whose key cannot be resolved **fails startup** rather than being skipped
    or wired with an empty credential (ADR-0009 row 16: "secrets manager unreachable at startup ->
    fail fast"). Skipping it would silently shrink the routable set and surface later as a
    mysterious ``no_eligible_provider``; an empty credential would surface as an unexplained 401
    from the provider on every request. Both hide a misconfiguration the operator can fix now.

    A provider with no ``base_url`` is likewise a configuration error, not a default to guess at.
    """
    connections: dict[str, ProviderConnection] = {}
    for name, connection in settings.providers.items():
        if not connection.base_url:
            raise SecretNotFoundError(
                f"provider {name!r} has no base_url configured "
                f"(set GATEWAY_PROVIDERS__{name.upper()}__BASE_URL)."
            )
        api_key = secrets.try_resolve(connection.api_key_ref) if connection.api_key_ref else None
        if api_key is None:
            raise SecretNotFoundError(
                f"provider {name!r} credential {connection.api_key_ref!r} could not be resolved; "
                "a provider configured with an unusable credential would fail every call "
                "(ADR-0011 / ADR-0009 row 16)."
            )
        connections[name] = ProviderConnection(
            base_url=connection.base_url,
            api_key=api_key,
            timeout_seconds=connection.timeout_seconds,
        )
    return connections


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
    authenticator: Authenticator
    audit_sink: AuthAuditSink
    state_signer: StateSigner
    circuit_breaker: CircuitBreaker
    routing_engine: RoutingEngine
    routing_stage: AgentRoutingStage
    provider_client: ProviderClient
    streaming_provider_client: StreamingProviderClient
    provider_executor: ProviderExecutor
    streaming_executor: StreamingProviderExecutor
    pricing_port: PricingPort
    cost_accountant: CostAccountant
    ledger_port: BudgetLedgerPort
    reservation_reconciler: ReservationReconciler
    reservation_service: ReservationService
    cache_port: ResponseCachePort
    deduplicator: RequestDeduplicator
    inference_coordinator: InferenceCoordinator
    streaming_coordinator: StreamingCoordinator
    sleeper: Sleeper
    retry_policy: RetryPolicy
    reflective_executor: ReflectiveExecutor
    evaluators: tuple[Evaluator, ...]
    evaluation_runner: EvaluationRunner
    policy_engine: PolicyEnginePort
    policy_stage: PolicyStage
    permission_resolver: PermissionResolver
    authorization_stage: AuthorizationStage
    request_pipeline: RequestPipeline
    inference_service: InferenceService

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
        # Slice 17: the middleware finally has an Authenticator to be wired with. JWT only -
        # API-key credentials need a request-scoped ApiKeyRepository, which is Slice 18's durable
        # storage work; an unverifiable credential fails closed rather than being waved through.
        # Slice 18: API keys are verifiable at last. CompositeAuthenticator routes `elg_`-prefixed
        # credentials to the key use-case and everything else to the token verifier; the key path
        # needs durable storage, and reaching it under RLS needs the ADR-0019 bootstrap lookup,
        # which exists only on PostgreSQL. Without Postgres the deployment keeps the JWT-only
        # authenticator rather than pretending to verify a credential type it cannot read - an
        # API key then fails closed with a 401, exactly as it did before this slice.
        authenticator: Authenticator = (
            CompositeAuthenticator(
                AuthenticateApiKey(TenantScopedApiKeyRepository(uow_factory), clock),
                token_service,
            )
            if rls_enabled
            else BearerTokenAuthenticator(token_service)
        )
        # Slice 18: the composite finally has something to fan out to. The durable sink writes the
        # hash-chained audit_event log; the logging sink stays because it is the ONLY record of an
        # authentication rejection, which has no proven tenant and therefore no tenant-scoped log
        # to be appended to (see SqlAuthAuditSink's docstring). Order matters for neither, but the
        # composite's failure isolation does: a database hiccup must alert, not break login
        # (ADR-0009 row 7, inference-side "buffer+alert").
        audit_sinks: list[AuthAuditSink] = [LoggingAuthAuditSink()]
        if rls_enabled:
            audit_sinks.append(SqlAuthAuditSink(uow_factory, clock))
        audit_sink: AuthAuditSink = CompositeAuthAuditSink(audit_sinks)
        # Signs the tenant hint inside the OIDC ``state`` so the callback can resolve the org
        # before any DB access. Resolved from the secrets manager in production (ADR-0011);
        # a per-process ephemeral key is used only when no reference is configured, which
        # confines any such deployment to a single instance by construction.
        state_signer = StateSigner(_resolve_state_signing_key(auth, secrets))

        # --- routing object graph (ADR-0016 Slice 6; durable catalog Slice 19) -----------
        # The composition root is the only place any of these may be built (Guards K and L).
        # Slice 19: on PostgreSQL the catalog reads the tenant's provider/model rows, so routing
        # finally has something to choose between and FR-028's runtime enable/disable takes effect
        # without a redeploy. Without Postgres the in-memory catalog remains, and it starts empty:
        # routing then yields NO_CANDIDATE, an explained refusal rather than a crash, and the
        # correct behaviour for a gateway with nothing to route to.
        provider_catalog: ProviderCatalog = (
            SqlProviderCatalog(uow_factory) if rls_enabled else InMemoryProviderCatalog()
        )
        # Slice 20: one circuit breaker, shared by the HealthAgent that READS it at routing time
        # and the InferenceCoordinator that WRITES call outcomes to it at settlement time. A single
        # instance is the whole point - a component that built its own would split the feedback
        # loop (a construction guard enforces that only this line may build one). In-process and
        # per-(org, provider); durable cross-replica snapshots await ADR-0005 (see the port).
        circuit_breaker: CircuitBreaker = InMemoryCircuitBreaker(clock)
        # Slice 21: adaptive routing. The strategy ranks the usable candidates the HealthAgent
        # reports (healthy over degraded), so a recovering provider is preferred last rather than
        # picked first. Stateless and pure, so it needs no construction guard - swapping it for a
        # future strategy (ADR-0012's lowest_cost / lowest_latency, or the deferred bandit) is one
        # line here and nothing else, which is the whole point of the RoutingStrategy port.
        routing_strategy: RoutingStrategy = HealthTieredRoutingStrategy()
        agent_runtime = AgentRuntime(
            [
                PlannerAgent(),
                PolicyAgent(),
                CostAgent(),
                HealthAgent(breaker=circuit_breaker),
                ProviderAgent(strategy=routing_strategy),
            ],
            clock,
        )
        routing_engine: RoutingEngine = AgentOrchestratedRoutingEngine(
            provider_catalog, agent_runtime
        )
        routing_stage = AgentRoutingStage(routing_engine)

        # --- provider execution object graph (ADR-0016 Slice 7; real adapter Slice 19) ----
        # The composition root is the only place either may be built (Guard 1). Slice 19 realizes
        # ADR-0003: when connections are configured, the OpenAI-compatible HTTP adapter makes the
        # real call. Credentials are resolved here, from the secrets manager, and never leave the
        # adapter.
        #
        # Phase 5 M1: ONE client object, bound to TWO ports. ProviderClient and
        # StreamingProviderClient are separate protocols on purpose (a provider able to do only one
        # must be expressible), but the adapter that can do both is one integration, and building
        # two instances of it would open two connection pools against the same provider.
        #
        # Phase 5 M2: with no connections configured the fallback FAILS CLOSED. It used to be
        # InMemoryProviderClient, which "always succeeds" and synthesizes usage - so a production
        # deployment with a seeded catalog and no connections answered every request 200 with
        # invented content and booked real spend for it. The synthesizing client is still
        # available, but only to a deployment that asked for it in as many words (and never in
        # production - the settings validator refuses).
        provider_connections = _build_provider_connections(settings, secrets)
        provider_client: ProviderClient
        streaming_provider_client: StreamingProviderClient
        if provider_connections:
            http_client = OpenAiCompatibleProviderClient(provider_connections)
            provider_client = http_client
            streaming_provider_client = http_client
        elif settings.allow_fake_provider_client:
            get_logger("bootstrap").warning(
                "fake_provider_client_enabled",
                reason="no provider connections configured; inference responses are FABRICATED "
                "and spend booked against them is not real (DEV/TEST ONLY)",
            )
            in_memory_client = InMemoryProviderClient()
            provider_client = in_memory_client
            streaming_provider_client = in_memory_client
        else:
            unconfigured = UnconfiguredProviderClient()
            provider_client = unconfigured
            streaming_provider_client = unconfigured
        provider_executor = ProviderExecutor(provider_client)
        streaming_executor = StreamingProviderExecutor(streaming_provider_client)

        # --- usage/cost accounting object graph (Slice 8; durable pricing Slice 19) -------
        # The composition root is the only place any of these may be built (Guard 1). Slice 19:
        # on PostgreSQL the price list is the tenant's effective-dated price_table rows, so a
        # settled cost is reproducible against the price that was in force when the call happened
        # (FR-074/075).
        #
        # Phase 5 M2: BudgetPort/BudgetEnforcer/InMemoryBudgetStore were built here and called by
        # nothing - ReservationService/BudgetLedgerPort superseded them in Slice 9. They are gone;
        # the ledger below is the sole budget authority.
        pricing_port: PricingPort = (
            SqlPriceTable(uow_factory, clock) if rls_enabled else StaticPriceTable()
        )
        cost_accountant = CostAccountant(pricing_port)

        # --- durable budget ledger / reservation object graph (ADR-0017, Slice 9) -------
        # Real reserve/commit atomicity is a PostgreSQL guarantee (row-level locking inside one
        # transaction) - SqlBudgetLedger only proves anything against a real Postgres engine. The
        # in-memory fallback (SQLite/local dev without Postgres) satisfies Rule 4's second
        # implementation and lets ReservationService be exercised without a database, but does
        # NOT prove atomicity (see its docstring) - only the Postgres path does.
        ledger_port: BudgetLedgerPort = (
            SqlBudgetLedger(uow_factory) if rls_enabled else InMemoryBudgetLedger()
        )
        # Phase 5 M2: the crash-safety debt from Slice 9. A hold whose owner died is returned by
        # the reconciler, which ReservationService.reserve calls for the tenant it is about to
        # reserve for - tenant-scoped, so RLS covers it, and self-scheduling, so no background
        # worker had to be invented to own it (see the reconciler's docstring).
        reservation_reconciler = ReservationReconciler(
            ledger_port, clock, timedelta(seconds=settings.reservation_ttl_seconds)
        )
        reservation_service = ReservationService(
            ledger_port, pricing_port, cost_accountant, reservation_reconciler
        )

        # --- response cache / request deduplication object graph (ADR-0016 Slice 10) -----
        # Same rationale as ledger_port above: the cache's tenant-isolation claim (RLS) only
        # holds against real Postgres (ADR-0018). The in-memory fallback satisfies Rule 4's
        # second implementation and lets InferenceCoordinator be exercised without a database,
        # but proves nothing about RLS - only the Postgres path does.
        cache_port: ResponseCachePort = (
            SqlResponseCache(uow_factory, clock) if rls_enabled else InMemoryResponseCache(clock)
        )
        deduplicator = RequestDeduplicator()
        inference_coordinator = InferenceCoordinator(
            cache_port, deduplicator, reservation_service, provider_executor, circuit_breaker
        )

        # --- streamed inference object graph (Phase 5 M1) --------------------------------
        # The same cache, the same ReservationService and the same circuit breaker instance the
        # unary path uses - streaming adds a delivery shape, not a second set of capabilities.
        # No deduplicator: a stream is an iterator, and two callers cannot share one without one
        # of them stealing the other's chunks (see StreamingCoordinator's docstring).
        streaming_coordinator = StreamingCoordinator(
            cache_port, reservation_service, streaming_executor, circuit_breaker
        )

        # --- reflection / bounded retry object graph (ADR-0016 Slice 11) -----------------
        # The coordinator is reflection's ONLY collaborator: every attempt goes back through
        # the same cache -> budget -> provider path, so a retry cannot bypass any of them.
        # Defaults are conservative (3 attempts, 100ms exponential base) and typed, not magic
        # numbers scattered through the executor.
        sleeper: Sleeper = AsyncioSleeper()
        retry_policy = RetryPolicy()
        reflective_executor = ReflectiveExecutor(inference_coordinator, retry_policy, sleeper)

        # --- evaluation object graph (ADR-0016 Slice 12) ---------------------------------
        # Post-hoc observation only: the runner is handed completed outcomes and can reach
        # nothing else (import-linter, Slice 12). Both evaluators are deterministic and pure -
        # no LLM judge, no external model, no new data (Rule 5). Declared order is the order
        # they run in, so reports are byte-identical across runs.
        evaluators: tuple[Evaluator, ...] = (
            ResponseCompletenessEvaluator(),
            UsageAccountingConsistencyEvaluator(),
        )
        evaluation_runner = EvaluationRunner(evaluators)

        # --- policy engine object graph (ADR-0016 Slice 13) ------------------------------
        # PolicyStage implements the Tier-1 PipelineStage seam UNCHANGED - the architectural
        # hypothesis ADR-0016 made when it demoted Policy Engine to Tier 2. The engine is local
        # and deterministic; OPA is deliberately deferred (no server, no bundle, no consumer -
        # see LocalPolicyEngine's docstring), and substituting it later changes only this line.
        policy_engine: PolicyEnginePort = LocalPolicyEngine()
        policy_stage = PolicyStage(policy_engine)

        # --- request admission pipeline (ADR-0016 invariant 5, Slice 14) -----------------
        # The executor invariant 5 always required ("stage registration + ordering") and never
        # had. Until this line, AuthorizationStage (Slice 5) was not constructed anywhere and
        # PolicyStage (Slice 13) was constructed but never run: both were enforced by
        # construction and unenforced in traffic.
        #
        # Slice 18: RBAC has storage. On PostgreSQL the resolver reads the seeded ADR-0008 role
        # matrix and virtual-key scopes, so a principal who has actually been granted something
        # now resolves to it. Without Postgres there is nowhere to read from, and the fail-closed
        # NullPermissionResolver remains - an unwired RBAC subsystem must deny every request,
        # never allow every one. Substituting one for the other is the single line the Slice-5
        # port was introduced to buy.
        #
        # Order is derived, not assumed:
        #   1. authorization - may this principal act at all? The cheapest question that can
        #      refuse, and the one whose answer does not depend on the request's content. A
        #      caller who may not act should never reach a control that reveals what the
        #      deployment's limits are.
        #   2. policy        - is this request admissible? Identity-independent, and its denial
        #      discloses a threshold (indirectly), so it runs behind authorization.
        #   3. routing       - transports a RoutingDecision. It runs LAST among the three and
        #      only for an admitted request, because it is the one stage with a real downstream
        #      side effect: it invokes the routing engine, which runs the entire agent chain.
        #      "Authorization denial => no routing" is exactly this ordering plus the runner's
        #      first-block-wins rule, and it is what closes the Slice 5-13 bypass.
        permission_resolver: PermissionResolver = (
            SqlPermissionResolver(uow_factory) if rls_enabled else NullPermissionResolver()
        )
        authorization_stage = AuthorizationStage(permission_resolver)
        request_pipeline = RequestPipeline((authorization_stage, policy_stage, routing_stage))

        # --- served inference path (ADR-0016 Slice 15) -----------------------------------
        # Joins admission to the execution path that has existed since Slice 9 but was reachable
        # only from tests. Three collaborators, each already the owner of its question; this
        # object adds none of its own. A refused request never reaches the executor at all, so
        # "denied => no reservation, no provider call, no settlement" is a structural property of
        # the composition rather than a rule someone has to remember.
        inference_service = InferenceService(
            request_pipeline, reflective_executor, evaluation_runner, streaming_coordinator
        )

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
            authenticator=authenticator,
            audit_sink=audit_sink,
            state_signer=state_signer,
            circuit_breaker=circuit_breaker,
            routing_engine=routing_engine,
            routing_stage=routing_stage,
            provider_client=provider_client,
            streaming_provider_client=streaming_provider_client,
            provider_executor=provider_executor,
            streaming_executor=streaming_executor,
            pricing_port=pricing_port,
            cost_accountant=cost_accountant,
            ledger_port=ledger_port,
            reservation_reconciler=reservation_reconciler,
            reservation_service=reservation_service,
            cache_port=cache_port,
            deduplicator=deduplicator,
            inference_coordinator=inference_coordinator,
            streaming_coordinator=streaming_coordinator,
            sleeper=sleeper,
            retry_policy=retry_policy,
            reflective_executor=reflective_executor,
            evaluators=evaluators,
            evaluation_runner=evaluation_runner,
            policy_engine=policy_engine,
            policy_stage=policy_stage,
            permission_resolver=permission_resolver,
            authorization_stage=authorization_stage,
            request_pipeline=request_pipeline,
            inference_service=inference_service,
        )

    async def dispose(self) -> None:
        """Release owned resources (connection pool). Called on app shutdown."""
        await self.engine.dispose()
