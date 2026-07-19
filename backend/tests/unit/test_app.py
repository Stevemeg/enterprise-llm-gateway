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
