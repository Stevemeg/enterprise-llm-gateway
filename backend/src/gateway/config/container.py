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
from gateway.adapters.budget.in_memory_budget_store import InMemoryBudgetStore
from gateway.adapters.cache.in_memory_response_cache import InMemoryResponseCache
from gateway.adapters.cache.sql_response_cache import SqlResponseCache
from gateway.adapters.ledger.in_memory_budget_ledger import InMemoryBudgetLedger
from gateway.adapters.ledger.sql_budget_ledger import SqlBudgetLedger
from gateway.adapters.persistence.engine import create_database_engine, create_session_factory
from gateway.adapters.persistence.health import DatabaseHealthCheck
from gateway.adapters.persistence.uow import UnitOfWorkFactory
from gateway.adapters.pipeline.policy_stage import PolicyStage
from gateway.adapters.pipeline.routing_stage import AgentRoutingStage
from gateway.adapters.policy.local_policy_engine import LocalPolicyEngine
from gateway.adapters.pricing.static_price_table import StaticPriceTable
from gateway.adapters.providers.in_memory_client import InMemoryProviderClient
from gateway.adapters.secrets.env_resolver import EnvSecretsResolver
from gateway.adapters.security.jwt import JwtService
from gateway.adapters.security.key_provider import KeyProvider
from gateway.adapters.security.keys import derive_public_pem
from gateway.adapters.security.oidc_state import StateSigner
from gateway.adapters.security.token_service import JwtTokenService
from gateway.application.accounting.budget_enforcer import BudgetEnforcer
from gateway.application.accounting.cost_accountant import CostAccountant
from gateway.application.accounting.reservation_service import ReservationService
from gateway.application.agents.cost import CostAgent
from gateway.application.agents.health import HealthAgent
from gateway.application.agents.planner import PlannerAgent
from gateway.application.agents.policy import PolicyAgent
from gateway.application.agents.provider import ProviderAgent
from gateway.application.agents.runtime import AgentRuntime
from gateway.application.evaluation.response_completeness import ResponseCompletenessEvaluator
from gateway.application.evaluation.runner import EvaluationRunner
from gateway.application.evaluation.usage_consistency import UsageAccountingConsistencyEvaluator
from gateway.application.execution.deduplicator import RequestDeduplicator
from gateway.application.execution.inference_coordinator import InferenceCoordinator
from gateway.application.ports.auth import AuthAuditSink
from gateway.application.ports.budget import BudgetPort
from gateway.application.ports.cache import ResponseCachePort
from gateway.application.ports.evaluation import Evaluator
from gateway.application.ports.ledger import BudgetLedgerPort
from gateway.application.ports.policy import PolicyEnginePort
from gateway.application.ports.pricing import PricingPort
from gateway.application.ports.providers import ProviderClient
from gateway.application.ports.routing import RoutingEngine
from gateway.application.ports.secrets import SecretNotFoundError, SecretsResolver
from gateway.application.providers.provider_executor import ProviderExecutor
from gateway.application.reflection.reflective_executor import ReflectiveExecutor
from gateway.application.reflection.retry_policy import RetryPolicy
from gateway.application.routing.catalog import InMemoryProviderCatalog
from gateway.application.routing.engine import AgentOrchestratedRoutingEngine
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
    routing_engine: RoutingEngine
    routing_stage: AgentRoutingStage
    provider_client: ProviderClient
    provider_executor: ProviderExecutor
    pricing_port: PricingPort
    budget_port: BudgetPort
    cost_accountant: CostAccountant
    budget_enforcer: BudgetEnforcer
    ledger_port: BudgetLedgerPort
    reservation_service: ReservationService
    cache_port: ResponseCachePort
    deduplicator: RequestDeduplicator
    inference_coordinator: InferenceCoordinator
    sleeper: Sleeper
    retry_policy: RetryPolicy
    reflective_executor: ReflectiveExecutor
    evaluators: tuple[Evaluator, ...]
    evaluation_runner: EvaluationRunner
    policy_engine: PolicyEnginePort
    policy_stage: PolicyStage

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

        # --- routing object graph (ADR-0016 Slice 6) ------------------------------------
        # The composition root is the only place any of these may be built (Guards K and L).
        # The catalog starts empty because no provider configuration exists yet: routing then
        # yields NO_CANDIDATE, which is an explained refusal rather than a crash, and is the
        # correct behaviour for a gateway with nothing to route to.
        provider_catalog = InMemoryProviderCatalog()
        agent_runtime = AgentRuntime(
            [PlannerAgent(), PolicyAgent(), CostAgent(), HealthAgent(), ProviderAgent()], clock
        )
        routing_engine: RoutingEngine = AgentOrchestratedRoutingEngine(
            provider_catalog, agent_runtime
        )
        routing_stage = AgentRoutingStage(routing_engine)

        # --- provider execution object graph (ADR-0016 Slice 7) -------------------------
        # The composition root is the only place either may be built (Guard 1). No real
        # provider SDK exists yet (that is provider-abstraction work), so the in-memory client
        # is the current default - it validates the port, not a production integration.
        provider_client: ProviderClient = InMemoryProviderClient()
        provider_executor = ProviderExecutor(provider_client)

        # --- usage/cost accounting object graph (ADR-0016 Slice 8) -----------------------
        # The composition root is the only place any of these may be built (Guard 1). Both
        # adapters start empty: no price list and no budgets are configured yet, so accounting
        # would raise UnknownPriceError and enforcement would allow (unbounded) - the same
        # "nothing configured yet" posture as the routing catalog above, not a defect.
        pricing_port: PricingPort = StaticPriceTable()
        budget_port: BudgetPort = InMemoryBudgetStore()
        cost_accountant = CostAccountant(pricing_port)
        budget_enforcer = BudgetEnforcer(budget_port)

        # --- durable budget ledger / reservation object graph (ADR-0017, Slice 9) -------
        # Real reserve/commit atomicity is a PostgreSQL guarantee (row-level locking inside one
        # transaction) - SqlBudgetLedger only proves anything against a real Postgres engine. The
        # in-memory fallback (SQLite/local dev without Postgres) satisfies Rule 4's second
        # implementation and lets ReservationService be exercised without a database, but does
        # NOT prove atomicity (see its docstring) - only the Postgres path does.
        ledger_port: BudgetLedgerPort = (
            SqlBudgetLedger(uow_factory) if rls_enabled else InMemoryBudgetLedger()
        )
        reservation_service = ReservationService(ledger_port, pricing_port, cost_accountant)

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
            cache_port, deduplicator, reservation_service, provider_executor
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
            routing_engine=routing_engine,
            routing_stage=routing_stage,
            provider_client=provider_client,
            provider_executor=provider_executor,
            pricing_port=pricing_port,
            budget_port=budget_port,
            cost_accountant=cost_accountant,
            budget_enforcer=budget_enforcer,
            ledger_port=ledger_port,
            reservation_service=reservation_service,
            cache_port=cache_port,
            deduplicator=deduplicator,
            inference_coordinator=inference_coordinator,
            sleeper=sleeper,
            retry_policy=retry_policy,
            reflective_executor=reflective_executor,
            evaluators=evaluators,
            evaluation_runner=evaluation_runner,
            policy_engine=policy_engine,
            policy_stage=policy_stage,
        )

    async def dispose(self) -> None:
        """Release owned resources (connection pool). Called on app shutdown."""
        await self.engine.dispose()
