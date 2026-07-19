"""Operational HTTP routes: ``/healthz``, ``/readyz``, ``/livez``, ``/metrics``.

Unversioned and unauthenticated (network-restricted in deployment) per the API design
(API_Design_Guide.md §1). Health/readiness reflect registered dependency checks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette import status

from gateway.application.ports.health import HealthState
from gateway.delivery.http.ops.health import HealthRegistry, HealthReport


def _report_payload(report: HealthReport) -> dict[str, Any]:
    return {
        "status": report.status.value,
        "version": report.version,
        "checked_at": report.checked_at,
        "checks": [
            {"name": component.name, "status": component.state.value, "detail": component.detail}
            for component in report.components
        ],
    }


def build_ops_router(registry: HealthRegistry) -> APIRouter:
    """Build the ops router bound to a health registry (dependency-injected)."""
    router = APIRouter(tags=["Health"])

    @router.get("/livez", summary="Liveness probe")
    async def livez() -> dict[str, str]:
        return {"status": "alive"}

    @router.get("/readyz", summary="Readiness probe")
    async def readyz() -> Response:
        report = await registry.run()
        code = status.HTTP_200_OK if report.is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(_report_payload(report), status_code=code)

    @router.get("/healthz", summary="Aggregate health")
    async def healthz() -> Response:
        report = await registry.run()
        healthy = report.status is not HealthState.DOWN
        code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(_report_payload(report), status_code=code)

    @router.get("/metrics", summary="Prometheus metrics exposition")
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
