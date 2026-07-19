"""Request-context middleware — stage 1 of the pipeline (Guide §13).

Accepts or generates an ``X-Request-Id``, binds it (plus method/path) to the logging
context so every downstream log line is correlated (FR-080), echoes it on the response,
and emits one structured access-log line per request. Later stages (auth, tenant,
authz, rate-limit, idempotency) are added in their milestones.
"""

from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from gateway.observability.logging import (
    bind_request_context,
    clear_request_context,
    get_logger,
)
from gateway.shared.types import RequestId

_REQUEST_ID_HEADER = "X-Request-Id"
_logger = get_logger("http.access")


def _new_request_id() -> RequestId:
    return RequestId(f"req_{uuid4().hex}")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id and log request completion."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get(_REQUEST_ID_HEADER)
        request_id: RequestId = RequestId(supplied) if supplied else _new_request_id()
        request.state.request_id = request_id
        bind_request_context(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers[_REQUEST_ID_HEADER] = request_id
            _logger.info(
                "http_request",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            clear_request_context()
