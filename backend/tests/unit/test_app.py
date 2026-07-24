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
    ):
        assert series in body
