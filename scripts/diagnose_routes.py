#!/usr/bin/env python3
"""Print the real route table for both app-construction paths.

test_route_auth_coverage builds the app via build_http_app() and sees no ops routes, while
test_app builds it via create_app() and its /livez, /healthz, /metrics tests pass. Both paths
call the same build_http_app(), so the difference must be observed rather than reasoned about.

Run:  uv run python ../scripts/diagnose_routes.py     (from backend/)
"""

from __future__ import annotations

from datetime import UTC, datetime


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _paths(app: object) -> list[str]:
    return sorted(str(getattr(r, "path", "?")) for r in app.routes)  # type: ignore[attr-defined]


def main() -> int:
    from gateway.delivery.http.app import build_http_app
    from gateway.delivery.http.ops.health import HealthRegistry
    from gateway.delivery.http.ops.router import build_ops_router

    registry = HealthRegistry(version="diag", clock=_Clock())

    router = build_ops_router(registry)
    print("1. build_ops_router() routes directly:")
    print("   ", sorted(str(getattr(r, "path", "?")) for r in router.routes) or "EMPTY")

    direct = build_http_app(
        service_name="diag", service_version="diag", health_registry=registry
    )
    print("\n2. build_http_app() (what the failing test uses):")
    print("   ", _paths(direct))

    try:
        from gateway.config.bootstrap import create_app
        from gateway.config.settings import (
            AuthSettings,
            DatabaseSettings,
            Environment,
            Settings,
        )

        settings = Settings(
            environment=Environment.DEVELOPMENT,
            log_json=True,
            database=DatabaseSettings(url="sqlite+aiosqlite:///:memory:"),
            auth=AuthSettings(allow_insecure_generated_keys=True),
        )
        print("\n3. create_app() (what the PASSING tests use):")
        print("   ", _paths(create_app(settings)))
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        print(f"\n3. create_app() failed: {type(exc).__name__}: {exc}")

    print("\nIf (1) is EMPTY -> build_ops_router registers nothing.")
    print("If (1) has routes but (2) does not -> include_router is not taking effect.")
    print("If (2) and (3) differ -> the two construction paths genuinely diverge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
