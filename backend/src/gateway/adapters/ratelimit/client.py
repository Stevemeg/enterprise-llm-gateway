"""Redis connection factory (Phase 5 M4, ADR-0021).

Separate from the limiter for the same reason ``create_database_engine`` is separate from every
repository: connection lifetime is the composition root's concern, and a component that opened its
own pool would leak one per instance and disappear from ``Container.dispose``.

It takes **primitives, not a settings object** - matching ``create_database_engine`` exactly, and
for a structural reason rather than symmetry: ``gateway.adapters`` may not import ``gateway.config``
(import-linter). An adapter that accepted a ``RedisSettings`` would have inverted the dependency and
made the adapter layer aware of the composition root.

Timeouts are explicit and short, never the client library's defaults. The limiter runs in front of
every request, so a Redis that has stopped answering must fail *fast* into ADR-0021's degraded mode
rather than adding its own latency to the path it exists to make cheap. ``retry_on_timeout`` is
deliberately off: retrying inside a call the caller is already prepared to degrade from just
multiplies the delay before that degradation happens.
"""

from __future__ import annotations

from redis.asyncio import Redis


def create_redis_client(*, url: str, timeout_seconds: float) -> Redis:
    """Open the shared-state connection pool. The caller owns closing it."""
    return Redis.from_url(
        url,
        socket_timeout=timeout_seconds,
        socket_connect_timeout=timeout_seconds,
        retry_on_timeout=False,
        # The limiter's values are two numbers it parses itself; decoding is pure overhead.
        decode_responses=False,
    )
