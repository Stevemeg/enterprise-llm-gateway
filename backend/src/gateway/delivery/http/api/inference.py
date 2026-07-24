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
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gateway.application.authorization.requirements import declare
from gateway.application.ports.execution import ExecutionOutcome
from gateway.application.ports.pipeline import StageContext
from gateway.application.ports.policy import REQUEST_PAYLOAD_KEY
from gateway.application.ports.providers import InferenceRequest
from gateway.application.serving.inference_service import InferenceService, ServedInference

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
        {
            "error": {
                "type": error_type,
                "code": code,
                "message": message,
                "request_id": request_id,
                "retryable": retryable,
            }
        },
        status_code=status,
    )


def _translate_refusal(served: ServedInference, request_id: str) -> JSONResponse:
    """An admission refusal. 403 for every case: the caller may not learn which control refused."""
    return _error(
        status=403,
        error_type="permission_error",
        code="permission_denied",
        message=served.refusal_reason or "request was not admitted",
        request_id=request_id,
    )


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
}


def build_inference_router(service: InferenceService) -> APIRouter:
    """Build the inference router bound to the composed service (dependency-injected)."""
    router = APIRouter(tags=["Inference"])

    @router.post(INFERENCE_PATH, summary="Execute one inference request")
    async def infer(request: Request, body: InferenceBody) -> JSONResponse:
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

        payload: dict[str, Any] = body.model_dump(exclude_none=True)
        context = StageContext(
            correlation_id=request_id,
            organization_id=auth.organization_id,
            principal_id=auth.principal_id,
            attributes={
                **declare(INFERENCE_PERMISSION, resource=f"POST {INFERENCE_PATH}"),
                REQUEST_PAYLOAD_KEY: payload,
            },
        )

        served = await service.serve(
            context, InferenceRequest(correlation_id=request_id, payload=payload)
        )

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
