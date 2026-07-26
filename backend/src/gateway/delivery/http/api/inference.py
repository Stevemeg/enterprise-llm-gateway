"""``POST /v1/inference`` - the first authenticated request path (ADR-0016 Slice 17).

Slices 1-16 built an entire admission-and-execution path that **nothing could call**: no route
referenced ``InferenceService``, and ``AuthenticationMiddleware`` was implemented, unit-tested and
never added to the ASGI app. This module is the caller, and wiring the middleware (in
``delivery/http/app.py``) is what turns an implemented control into an executing one.

## The delivery layer translates; it does not decide

This route contains **no** routing, provider selection, budget, policy, reflection or evaluation
logic - each already has an owner, and adding a second one here is the duplicated ownership the
whole phase has been arranged to prevent. What it does is exactly four things:

1. require an authenticated principal,
2. validate and translate the HTTP body into ``InferenceRequest`` / ``StageContext``,
3. call ``InferenceService.serve`` - the single composed path, never a second orchestration,
4. translate the result into the documented error model.

It reaches nothing else: ``gateway.delivery`` cannot import ``gateway.config`` (import-linter), it
constructs no ``RoutingDecision`` and references no ``AgentRuntime`` (reused AST guards), and its
only application collaborator is ``InferenceService``.

## Authentication is required *here*, deliberately

``AuthenticationMiddleware`` passes a credential-less request through by design - public routes
exist, and the middleware's own docstring says "protected routes enforce via dependencies". So a
missing ``request.state.auth`` is refused by this route rather than by the middleware. That keeps
the middleware's contract intact (verify a credential if one is presented; never invent an
authorization policy) and puts the "this endpoint is protected" decision in the endpoint, where it
is visible.

The route is **not** in ``PUBLIC_ROUTES``, so ``tests/security/test_route_auth_coverage.py`` - which
asserts behaviourally that an unauthenticated request must not receive 200 - now genuinely covers
it. That guard existed before this slice and had no protected route to protect.

## Status mapping (API_Error_Model.md §2, verbatim)

| Outcome | HTTP | ``type`` |
|---|---|---|
| no/invalid credential | 401 | ``authentication_error`` |
| admission refused (authorization or policy) | 403 | ``permission_error`` |
| budget exhausted | 402 | ``budget_error`` |
| budget ledger unavailable / nothing routable | 503 | ``availability_error`` |
| provider failed | 502 | ``provider_error`` |
| malformed body | 422 | ``validation_error`` |

A refusal keeps the reason the admission chain produced: those are already caller-safe (the stages
deliberately never name the missing permission, the rule or the threshold). This route adds no
detail of its own to a denial, so it cannot leak what the controls were careful not to.

## Phase 5 M1: ``"stream": true`` on the same endpoint

The streamed response is Server-Sent Events, per ``docs/API_Streaming.md`` §1 - a decision this
route *implements* rather than makes. SSE was chosen there over WebSocket and gRPC because
inference is unidirectional, proxy-friendly and OpenAI-shaped; nothing here revisits that.

It is a flag on the existing endpoint rather than a second path, so authentication, the declared
permission, the admission chain and the error envelope are literally the same code. A second route
would have been a second place for "this endpoint is protected" to be true or forgotten.

**Where the status code is decided is the whole design.** ``InferenceService.serve_stream`` returns
a session that has already run admission, the cache lookup, the budget reservation and the first
provider event - everything that can fail *before a byte is owed to the client*. So this route
still answers those with an ordinary JSON error and a real status code, exactly as the unary path
does and exactly as ``API_Streaming.md`` §2 requires. Only once the session is open does it commit
to ``200 text/event-stream``; from that instant a failure can only be a terminal ``event: error``,
because the status line is already sent and part of an answer is already in the client's hands.

This route still decides nothing else: it does not route, price, reserve, settle, retry, touch the
circuit breaker or know what a provider is. It frames owned events (``StreamChunk`` /
``StreamFailed`` from ``ports/streaming.py``) as SSE lines, and that is all.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from gateway.application.authorization.requirements import declare
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.pipeline import StageContext
from gateway.application.ports.policy import REQUEST_PAYLOAD_KEY
from gateway.application.ports.providers import InferenceRequest
from gateway.application.ports.streaming import InferenceStreamEvent, StreamChunk
from gateway.application.serving.inference_service import (
    InferenceService,
    ServedInference,
    ServedStream,
)

#: The permission this endpoint declares. ``AuthorizationStage`` refuses any request that declares
#: nothing, so an endpoint without this line is denied rather than silently public (Slice 5).
INFERENCE_PERMISSION = "inference:invoke"
INFERENCE_PATH = "/v1/inference"


class InferenceBody(BaseModel):
    """The accepted request body. Deliberately minimal (Slice 17 ships one endpoint).

    ``model`` and ``prompt`` are the two fields the routing and policy path already consume;
    nothing else is accepted, so an unexpected field is a 422 rather than an attribute quietly
    travelling into the payload the policy engine measures.
    """

    model_config = {"extra": "forbid"}

    prompt: str = Field(min_length=1)
    model: str | None = None
    #: Phase 5 M1. Deliberately excluded from the payload the policy engine and the cache key see
    #: (``_inference_payload``): how a response is *delivered* is not part of what was asked for,
    #: and letting it into the cache key would give every streamed request a permanent miss
    #: against the unary entry for the identical prompt.
    stream: bool = False


#: Framing headers for a streamed response (``docs/API_Streaming.md`` §1). ``X-Accel-Buffering``
#: is not decoration: an nginx-shaped intermediary buffers a response body by default, which turns
#: token streaming back into one delayed blob and silently undoes the entire milestone.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_DONE_SENTINEL = "[DONE]"
#: The one message a streamed provider failure may carry. Identical to the unary 502's text, and
#: for the identical reason: the provider's own error string is unbounded, provider-authored, and
#: may quote the request back.
_PROVIDER_FAILED = "The upstream provider failed to complete this request."


def _error_body(
    *, error_type: str, code: str, message: str, request_id: str, retryable: bool
) -> dict[str, Any]:
    """API_Error_Model.md's envelope as data, so a JSON response and a terminal SSE event cannot
    describe the same failure two different ways."""
    return {
        "error": {
            "type": error_type,
            "code": code,
            "message": message,
            "request_id": request_id,
            "retryable": retryable,
        }
    }


def _error(
    *,
    status: int,
    error_type: str,
    code: str,
    message: str,
    request_id: str,
    retryable: bool = False,
) -> JSONResponse:
    """Render API_Error_Model.md's envelope. Never includes stage names, rules or thresholds."""
    return JSONResponse(
        _error_body(
            error_type=error_type,
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
        ),
        status_code=status,
    )


def _translate_refusal(served: ServedInference | ServedStream, request_id: str) -> JSONResponse:
    """An admission refusal. 403 for every case: the caller may not learn which control refused.

    Shared by both delivery shapes deliberately: a refusal must look identical whether or not the
    caller asked to stream, or the flag would become a way to probe which control said no.
    """
    return _error(
        status=403,
        error_type="permission_error",
        code="permission_denied",
        message=served.refusal_reason or "request was not admitted",
        request_id=request_id,
    )


def _sse(data: str, *, event: str | None = None) -> str:
    """One SSE frame. Chunk text is JSON-encoded, so a newline in a token cannot forge a frame."""
    prefix = f"event: {event}\n" if event is not None else ""
    return f"{prefix}data: {data}\n\n"


async def _aclose(events: AsyncIterator[InferenceStreamEvent]) -> None:
    """Close the application's event stream when framing stops, so the reservation is finalized
    and the upstream call aborted *now* rather than whenever the loop gets around to it."""
    closer = getattr(events, "aclose", None)
    if closer is not None:
        await closer()


async def _frame(
    events: AsyncIterator[InferenceStreamEvent], request_id: str
) -> AsyncIterator[str]:
    """Translate owned events into SSE frames. Adds no decision - only framing."""
    try:
        async for event in events:
            if isinstance(event, StreamChunk):
                yield _sse(json.dumps({"delta": event.content}))
                continue
            # A terminal failure after the status line was already sent: the only honest ending
            # is an error event, and it carries this module's constant, never the provider's text.
            yield _sse(
                json.dumps(
                    _error_body(
                        error_type="provider_error",
                        code="provider_failed",
                        message=_PROVIDER_FAILED,
                        request_id=request_id,
                        retryable=True,
                    )
                ),
                event="error",
            )
            return
        yield _sse(_DONE_SENTINEL)
    finally:
        await _aclose(events)


def _inference_payload(body: InferenceBody) -> dict[str, Any]:
    """What was asked for, without how it should be delivered.

    ``stream`` is a transport preference. It is excluded so the policy engine measures the same
    request either way and - more importantly - so the cache key is identical, letting a streamed
    request be served from an entry a unary request populated, and the reverse.
    """
    return body.model_dump(exclude_none=True, exclude={"stream"})


_EXECUTION_ERRORS: dict[ExecutionOutcome, tuple[int, str, str, str, bool]] = {
    ExecutionOutcome.BUDGET_DENIED: (
        402,
        "budget_error",
        "budget_exceeded",
        "The organization's budget for this request is exhausted.",
        False,
    ),
    ExecutionOutcome.BUDGET_UNAVAILABLE: (
        503,
        "availability_error",
        "budget_unavailable",
        "Budget could not be verified, so the request was not executed.",
        True,
    ),
    ExecutionOutcome.NOT_ROUTED: (
        503,
        "availability_error",
        "no_eligible_provider",
        "No eligible provider is available for this request.",
        True,
    ),
    # Phase 5 M2. Previously this condition escaped as an uncaught accounting exception and
    # surfaced as a generic 500. It is not an unexpected fault: it is a deliberate fail-closed
    # refusal, so it belongs in the taxonomy rather than in the 500 bucket.
    #
    # 503 ``availability_error``, per API_Error_Model.md 2 - the deployment is "not ready" to
    # serve this model, which is exactly what a missing price-table row means, and the row's fail
    # mode is already "closed (ADR-0009)". ``retryable`` is **false**, deliberately and unlike the
    # other two 503s here: those clear on their own, and this one clears only when an operator
    # changes configuration, so telling a client to back off and retry would be a lie.
    #
    # The message names no model, no provider and no price table: a caller must not be able to
    # enumerate which models a deployment cannot price. Operators get the specifics from
    # ``inference_not_accountable`` in the log and from the metric label.
    ExecutionOutcome.NOT_ACCOUNTABLE: (
        503,
        "availability_error",
        "accounting_unavailable",
        "This request could not be accounted for and was not served.",
        False,
    ),
}


async def _stream_response(
    service: InferenceService,
    context: StageContext,
    inference_request: InferenceRequest,
    request_id: str,
) -> Response:
    """Serve the streamed shape. Everything answerable with a status code is answered here."""
    served = await service.serve_stream(context, inference_request)

    if not served.admitted:
        return _translate_refusal(served, request_id)

    # An admitted request always has a session (ServedStream enforces it).
    assert served.session is not None
    session = served.session

    mapped = _EXECUTION_ERRORS.get(session.outcome)
    if mapped is not None:
        status, error_type, code, message, retryable = mapped
        return _error(
            status=status,
            error_type=error_type,
            code=code,
            message=message,
            request_id=request_id,
            retryable=retryable,
        )

    if not session.opened:
        # The provider failed before producing anything: no byte is owed to the client yet, so
        # this is still an ordinary error response (API_Streaming.md §2).
        return _error(
            status=502,
            error_type="provider_error",
            code="provider_failed",
            message=_PROVIDER_FAILED,
            request_id=request_id,
            retryable=True,
        )

    assert session.events is not None
    return StreamingResponse(
        _frame(session.events, request_id),
        media_type="text/event-stream",
        headers={
            **_SSE_HEADERS,
            "X-Request-Id": request_id,
            "X-Cache": "hit" if session.outcome is ExecutionOutcome.CACHE_HIT else "miss",
        },
    )


def build_inference_router(service: InferenceService) -> APIRouter:
    """Build the inference router bound to the composed service (dependency-injected)."""
    router = APIRouter(tags=["Inference"])

    @router.post(INFERENCE_PATH, summary="Execute one inference request")
    async def infer(request: Request, body: InferenceBody) -> Response:
        request_id: str = getattr(request.state, "request_id", "unknown")

        auth = getattr(request.state, "auth", None)
        if auth is None:
            # The middleware lets credential-less requests through for public routes; this one is
            # not public. Fail closed here.
            return _error(
                status=401,
                error_type="authentication_error",
                code="authentication_required",
                message="This endpoint requires an authenticated principal.",
                request_id=request_id,
            )

        payload: dict[str, Any] = _inference_payload(body)
        context = StageContext(
            correlation_id=request_id,
            organization_id=auth.organization_id,
            principal_id=auth.principal_id,
            attributes={
                **declare(INFERENCE_PERMISSION, resource=f"POST {INFERENCE_PATH}"),
                REQUEST_PAYLOAD_KEY: payload,
            },
        )
        inference_request = InferenceRequest(correlation_id=request_id, payload=payload)

        if body.stream:
            # Same context, same request, same admission chain - only the delivery shape differs.
            return await _stream_response(service, context, inference_request, request_id)

        served = await service.serve(context, inference_request)

        if not served.admitted:
            return _translate_refusal(served, request_id)

        # An admitted request always has a reflection result (ServedInference enforces it).
        assert served.reflection is not None
        final = served.reflection.final

        mapped = _EXECUTION_ERRORS.get(final.outcome)
        if mapped is not None:
            status, error_type, code, message, retryable = mapped
            return _error(
                status=status,
                error_type=error_type,
                code=code,
                message=message,
                request_id=request_id,
                retryable=retryable,
            )

        if not final.response.ok:
            # The provider's own error text is never echoed: it is unbounded, provider-authored
            # and may quote the request back.
            return _error(
                status=502,
                error_type="provider_error",
                code="provider_failed",
                message="The upstream provider failed to complete this request.",
                request_id=request_id,
                retryable=True,
            )

        return JSONResponse(
            {
                "content": final.response.content,
                "provider": final.response.provider,
                "cached": final.outcome is ExecutionOutcome.CACHE_HIT,
                "attempts": served.reflection.attempt_count,
                "request_id": request_id,
            },
            status_code=200,
        )

    return router
