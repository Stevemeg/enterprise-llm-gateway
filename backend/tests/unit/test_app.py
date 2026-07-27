"""Tests for the wired HTTP application (ops endpoints + middleware)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.config.bootstrap import create_app
from gateway.config.settings import Settings


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def test_livez_returns_alive(test_settings: Settings) -> None:
    response = _client(test_settings).get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_healthz_ok_with_database_check(test_settings: Settings) -> None:
    response = _client(test_settings).get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == test_settings.service_version
    names = {check["name"] for check in body["checks"]}
    assert "database" in names


def test_request_id_is_generated_and_returned(test_settings: Settings) -> None:
    response = _client(test_settings).get("/livez")
    assert response.headers["X-Request-Id"].startswith("req_")


def test_supplied_request_id_is_echoed(test_settings: Settings) -> None:
    response = _client(test_settings).get("/livez", headers={"X-Request-Id": "req_supplied"})
    assert response.headers["X-Request-Id"] == "req_supplied"


def test_metrics_exposition(test_settings: Settings) -> None:
    response = _client(test_settings).get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_metrics_exposition_includes_the_request_path_series(test_settings: Settings) -> None:
    """Slice 16: ``/metrics`` was live but blind to Slices 5-15. These series make it useful."""
    body = _client(test_settings).get("/metrics").text

    for series in (
        "gateway_admission_stage_decisions_total",
        "gateway_served_requests_total",
        "gateway_served_request_duration_seconds",
        "gateway_inference_attempts_total",
        "gateway_cache_lookups_total",
        "gateway_provider_calls_total",
        "gateway_provider_call_duration_seconds",
        "gateway_reflection_attempts_total",
        "gateway_routing_decisions_total",
        "gateway_evaluations_total",
        "gateway_budget_reservations_total",
        # Phase 5 M3.
        "gateway_ingress_decisions_total",
    ):
        assert series in body


# --- Phase 5 M3: the chain a real process actually runs -----------------------------------------


def _middleware_chain(settings: Settings) -> list[str]:
    """Outermost-first names of the user middleware ``create_app`` installs.

    Read off the app rather than off ``build_http_app``'s source: the ordering claim is about what
    a *process* runs, and ``build_http_app``'s parameters are all optional, so a chain assembled
    from the real bootstrap is the only thing that can show a layer was forgotten.
    """
    return [getattr(m.cls, "__name__", repr(m.cls)) for m in create_app(settings).user_middleware]


def test_the_process_runs_all_four_middlewares_in_the_forced_order(
    test_settings: Settings,
) -> None:
    """Each position is forced by a constraint (see ``delivery/http/app.py``), so this is pinned
    rather than left to a comment:

    * request context outermost, or the two ingress refusals lose their ``X-Request-Id``;
    * the size limit outside authentication, or an unauthenticated oversized body costs a
      database lookup before being refused;
    * the rate limiter inside authentication, or its key does not exist yet.
    """
    assert _middleware_chain(test_settings) == [
        "RequestContextMiddleware",
        "RequestSizeLimitMiddleware",
        "AuthenticationMiddleware",
        "RateLimitMiddleware",
    ]


def test_ingress_protection_cannot_be_omitted_by_a_real_deployment(
    test_settings: Settings,
) -> None:
    """``build_http_app`` makes both controls optional so a focused test can build a chain without
    them. ``create_app`` must not: a limiter that is merely available is the "implemented but
    never invoked" failure this project keeps finding (``AuthenticationMiddleware`` shipped that
    way for an entire milestone)."""
    chain = _middleware_chain(test_settings)

    assert "RateLimitMiddleware" in chain
    assert "RequestSizeLimitMiddleware" in chain


def test_the_container_holds_exactly_one_rate_limiter(test_settings: Settings) -> None:
    """The single-instance property the construction guard enforces statically, observed on a
    real container: the app and the container must share one object, not two."""
    app = create_app(test_settings)
    container = app.state.container

    limiter = container.rate_limiter
    assert limiter is not None
    assert container.rate_limiter is limiter
