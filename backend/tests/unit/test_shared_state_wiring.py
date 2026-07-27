"""The composition-root swap and the degraded fallback (Phase 5 M4, ADR-0021).

The Redis behaviour itself is proven against a real server in
``tests/integration/test_shared_rate_limit_redis.py``. These cover the parts that are *not* about
Redis: which implementation the container selects, that the selection is invisible to everything
downstream, that the pool is closed on shutdown, and that the degraded fallback behaves as ADR-0021
decision 4 says - all of which must hold whether or not a Redis is running.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from gateway.adapters.ratelimit.degraded import DegradedRateLimiter
from gateway.adapters.ratelimit.health import SharedStateHealthCheck
from gateway.adapters.ratelimit.in_memory_token_bucket import InMemoryTokenBucketRateLimiter
from gateway.application.ports.health import HealthState
from gateway.application.ports.rate_limit import (
    RateLimitDecision,
    RateLimiterPort,
    RateLimiterUnavailableError,
    RateLimitPolicy,
)
from gateway.config.container import Container
from gateway.config.settings import (
    AuthSettings,
    DatabaseSettings,
    Environment,
    RedisSettings,
    Settings,
)
from gateway.delivery.http.ops.health import HealthRegistry
from tests.conftest import FixedClock

ORG = uuid4()


def _settings(**overrides: object) -> Settings:
    return Settings(
        environment=Environment.DEVELOPMENT,
        database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
        auth=AuthSettings(allow_insecure_generated_keys=True),
        **overrides,  # type: ignore[arg-type]
    )


def _local(*, burst: int = 2) -> RateLimiterPort:
    return InMemoryTokenBucketRateLimiter(
        FixedClock(), RateLimitPolicy(requests_per_second=1.0, burst=burst)
    )


class BrokenShared:
    """A shared limiter that can never answer."""

    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        self.calls += 1
        raise RateLimiterUnavailableError("store unreachable")


class WorkingShared:
    """A shared limiter that always answers, so "did the fallback run" is observable."""

    def __init__(self) -> None:
        self.calls = 0

    async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
        self.calls += 1
        return RateLimitDecision(allowed=True, limit=99, remaining=98, reset_seconds=1)


# ------------------------------------------------------------------ composition-root selection


def test_without_redis_the_container_wires_the_in_process_limiter() -> None:
    """The single-node profile must acquire no Redis dependency it did not ask for - the same
    posture ``rls_enabled`` takes for Sql* vs InMemory*."""
    container = Container.create(_settings())

    assert isinstance(container.rate_limiter, InMemoryTokenBucketRateLimiter)
    assert container.redis_client is None


def test_with_redis_configured_the_container_wires_the_shared_limiter() -> None:
    """ADR-0021's central claim, observed at the swap point. Constructing the container opens a
    pool but issues no command, so this needs no running Redis - which is itself the evidence that
    the *selection* is a composition-root decision and not a runtime probe."""
    container = Container.create(
        _settings(redis=RedisSettings(url="redis://127.0.0.1:6379/0", key_prefix="unit"))
    )

    assert isinstance(container.rate_limiter, DegradedRateLimiter)
    assert container.redis_client is not None


def test_the_swap_changes_nothing_the_port_can_observe() -> None:
    """Both wirings satisfy the M3 port, unmodified. This is the property that made the milestone
    possible for the limiter and impossible for the circuit breaker and the deduplicator."""
    local_only = Container.create(_settings())
    shared = Container.create(
        _settings(redis=RedisSettings(url="redis://127.0.0.1:6379/0", key_prefix="unit"))
    )

    assert isinstance(local_only.rate_limiter, RateLimiterPort)
    assert isinstance(shared.rate_limiter, RateLimiterPort)


async def test_dispose_closes_the_redis_pool() -> None:
    """A pool nobody closes is a leak on every reload. The engine has been disposed since Slice 1
    for the same reason; M4 must not introduce a second resource that is not.

    Asserted by observing the close rather than by probing the client afterwards: redis-py
    transparently reconnects a closed client, so "ping fails" is not a fact about whether the pool
    was released.
    """
    container = Container.create(
        _settings(redis=RedisSettings(url="redis://127.0.0.1:6379/0", key_prefix="unit"))
    )
    client = container.redis_client
    assert client is not None
    closed: list[str] = []
    original = client.aclose

    async def record(*args: object, **kwargs: object) -> None:
        closed.append("redis")
        await original()

    client.aclose = record  # type: ignore[method-assign]

    await container.dispose()

    assert closed == ["redis"]


async def test_dispose_still_closes_the_database_pool_if_redis_objects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shutdown releases everything it can rather than stopping at the first resource that
    complains - otherwise one sulking dependency leaks the other. The ``finally`` in ``dispose``
    is what this pins, and without it a raising Redis close would strand the database pool."""
    container = Container.create(
        _settings(redis=RedisSettings(url="redis://127.0.0.1:6379/0", key_prefix="unit"))
    )
    assert container.redis_client is not None
    disposed: list[str] = []
    engine_dispose = AsyncEngine.dispose

    async def record_engine(self: AsyncEngine, close: bool = True) -> None:
        disposed.append("engine")
        await engine_dispose(self, close)

    async def explode(*args: object, **kwargs: object) -> None:
        raise OSError("redis refused to close")

    monkeypatch.setattr(AsyncEngine, "dispose", record_engine)
    container.redis_client.aclose = explode  # type: ignore[method-assign]

    with pytest.raises(OSError, match="refused to close"):
        await container.dispose()

    assert disposed == ["engine"], "the database pool was stranded by a failing Redis close"


# ------------------------------------------------------------------ degraded fallback


async def test_the_shared_limiter_answers_when_it_can() -> None:
    shared = WorkingShared()
    limiter = DegradedRateLimiter(shared, _local())

    decision = await limiter.acquire(organization_id=ORG)

    assert decision.limit == 99, "the shared decision was not used"
    assert shared.calls == 1
    assert limiter.degraded is False


async def test_an_outage_falls_back_to_the_local_bucket() -> None:
    limiter = DegradedRateLimiter(BrokenShared(), _local(burst=2))

    assert (await limiter.acquire(organization_id=ORG)).allowed is True
    assert limiter.degraded is True


async def test_degraded_mode_still_limits_which_is_what_makes_it_not_fail_open() -> None:
    """The distinction ADR-0021 decision 4 rests on. Unlimited would be fail-open; a local bucket
    enforcing the same policy is degraded-closed."""
    limiter = DegradedRateLimiter(BrokenShared(), _local(burst=2))

    verdicts = [(await limiter.acquire(organization_id=ORG)).allowed for _ in range(5)]

    assert verdicts == [True, True, False, False, False]


async def test_degraded_mode_keeps_tenants_isolated() -> None:
    """Degrading must not also collapse the tenant boundary - that would turn an availability
    event into a cross-tenant one."""
    limiter = DegradedRateLimiter(BrokenShared(), _local(burst=1))
    other = uuid4()

    assert (await limiter.acquire(organization_id=ORG)).allowed is True
    assert (await limiter.acquire(organization_id=ORG)).allowed is False

    assert (await limiter.acquire(organization_id=other)).allowed is True


async def test_recovery_returns_to_the_shared_limiter() -> None:
    """A limiter that never left degraded mode would silently leave a deployment per-replica
    forever after one blip."""

    class Flaky:
        def __init__(self) -> None:
            self.fail = True

        async def acquire(self, *, organization_id: UUID) -> RateLimitDecision:
            if self.fail:
                raise RateLimiterUnavailableError("down")
            return RateLimitDecision(allowed=True, limit=99, remaining=98, reset_seconds=1)

    flaky = Flaky()
    limiter = DegradedRateLimiter(flaky, _local(burst=5))
    await limiter.acquire(organization_id=ORG)
    assert limiter.degraded is True

    flaky.fail = False
    decision = await limiter.acquire(organization_id=ORG)

    assert decision.limit == 99
    assert limiter.degraded is False


async def test_the_fallback_satisfies_the_unmodified_port() -> None:
    assert isinstance(DegradedRateLimiter(WorkingShared(), _local()), RateLimiterPort)


# ------------------------------------------------------------------ settings


def test_redis_is_unconfigured_by_default() -> None:
    assert RedisSettings().is_configured is False


def test_a_redis_password_is_redacted_before_it_can_be_logged() -> None:
    """``container_initialised`` logs the endpoint. A credential in a startup log is a credential
    in every log aggregator (NFR-SEC03), so the masked form is what the container reads."""
    settings = RedisSettings(url="redis://alice:sup3rs3cret@redis.internal:6379/0")

    assert settings.safe_url == "redis://alice:***@redis.internal:6379/0"
    assert "sup3rs3cret" not in settings.safe_url


def test_a_redis_url_without_a_credential_is_unchanged() -> None:
    assert RedisSettings(url="redis://localhost:6379/0").safe_url == "redis://localhost:6379/0"


def test_an_unconfigured_redis_has_no_url_to_leak() -> None:
    assert RedisSettings().safe_url == ""


# ------------------------------------------------------------------ operational visibility


async def test_a_single_node_deployment_reports_no_shared_state_component() -> None:
    """A check describing a component that does not exist would be worse than no check: it would
    report "ok" about shared state this process has none of.

    Asserted through the report rather than the registry's internals, so it is the operator's
    actual view that is pinned."""
    container = Container.create(_settings())

    report = await container.health.run()

    assert {c.name for c in report.components} == {"database"}


async def test_a_shared_deployment_reports_its_second_dependency() -> None:
    """M4 added an infrastructure dependency; /healthz listed one. An operator reading the surface
    built for that question must see both."""
    container = Container.create(
        _settings(redis=RedisSettings(url="redis://127.0.0.1:6379/0", key_prefix="unit"))
    )

    report = await container.health.run()

    assert {c.name for c in report.components} == {"database", "shared_rate_limit_state"}


async def test_a_degraded_store_shows_as_degraded_and_keeps_the_process_ready() -> None:
    """End to end through the real registry: ADR-0021's degradation must be *visible* without
    deregistering the replica. Reported DOWN, an orchestrator would evict a gateway that is still
    serving correctly - the outage the ADR chose degraded-closed to avoid."""
    limiter = DegradedRateLimiter(BrokenShared(), _local(burst=5))
    registry = HealthRegistry(version="test", clock=FixedClock())
    registry.register("shared_rate_limit_state", SharedStateHealthCheck(limiter))

    assert (await registry.run()).status is HealthState.OK, "nothing has failed yet"

    await limiter.acquire(organization_id=ORG)  # drives it into degraded mode
    report = await registry.run()

    assert report.status is HealthState.DEGRADED
    assert report.is_ready is True
    assert "per replica" in (report.components[0].detail or "")


async def test_a_healthy_store_reports_ok() -> None:
    """Falsifies the trivial pass: a check hard-wired to 'degraded' would satisfy the test above."""
    limiter = DegradedRateLimiter(WorkingShared(), _local())
    registry = HealthRegistry(version="test", clock=FixedClock())
    registry.register("shared_rate_limit_state", SharedStateHealthCheck(limiter))
    await limiter.acquire(organization_id=ORG)

    report = await registry.run()

    assert report.status is HealthState.OK
    assert report.components[0].state is HealthState.OK
