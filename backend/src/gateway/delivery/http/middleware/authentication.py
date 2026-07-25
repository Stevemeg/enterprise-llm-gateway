"""Authentication middleware — stage 4 of the pipeline (Guide §13, ADR-0008/0009).

Resolves the ``Authorization: Bearer`` credential to a principal via the injected
``Authenticator`` (API key or JWT). Behaviour:
* no credential -> pass through (public routes; protected routes enforce via dependencies);
* malformed header or invalid/expired credential -> **401, fail closed**, audited;
* success -> attach exactly one immutable ``AuthenticationContext`` and bind the log context.

Downstream code reads ``request.state.auth`` (the context object) rather than assorted
attributes — one typed contract, no attribute sprawl, and the input authorization will consume.

Every decision is recorded through the ``AuthAuditSink`` using an ``AuthenticationDecision``
(never an ad-hoc string) and timed into ``gateway_auth_duration_seconds``.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway.application.ports.auth import AuthAuditSink, Authenticator
from gateway.domain.auth.errors import AuthError, TokenExpiredError
from gateway.domain.auth.models import (
    AuthAuditEvent,
    AuthenticationContext,
    AuthenticationDecision,
    AuthenticationMethod,
    Principal,
    PrincipalType,
)
from gateway.observability.logging import bind_request_context
from gateway.observability.metrics import auth_duration_seconds
from gateway.shared.auth_constants import API_KEY_PREFIX

_HEADER = "Authorization"
_SCHEME = "Bearer "

_DECISION_TO_ERROR_CODE = {
    AuthenticationDecision.INVALID_TOKEN: "invalid_credential",
    AuthenticationDecision.EXPIRED: "token_expired",
    AuthenticationDecision.INTERNAL_ERROR: "authentication_unavailable",
}


def _method_for(credential: str) -> AuthenticationMethod:
    """Credential shape -> method label, for the case where authentication FAILS and there is no
    principal to ask. Both outcomes are closed, low-cardinality label values."""
    return (
        AuthenticationMethod.API_KEY
        if credential.startswith(API_KEY_PREFIX)
        else AuthenticationMethod.JWT
    )


def _method_for_principal(
    principal: Principal, fallback: AuthenticationMethod
) -> AuthenticationMethod:
    if principal.principal_type is PrincipalType.SERVICE_ACCOUNT:
        return AuthenticationMethod.SERVICE_ACCOUNT
    if principal.principal_type is PrincipalType.API_KEY:
        return AuthenticationMethod.API_KEY
    return fallback


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Attaches an ``AuthenticationContext`` or fails closed on a bad credential."""

    def __init__(self, app: object, *, authenticator: Authenticator, audit: AuthAuditSink) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._authenticator = authenticator
        self._audit = audit

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        header = request.headers.get(_HEADER)
        if header is None:
            return await call_next(request)
        if not header.startswith(_SCHEME):
            return await self._unauthorized(
                request,
                AuthenticationDecision.INVALID_TOKEN,
                AuthenticationMethod.JWT,
                message="Malformed Authorization header.",
                started=time.perf_counter(),
                code_override="invalid_authorization_header",
            )

        credential = header[len(_SCHEME) :].strip()
        method = _method_for(credential)
        started = time.perf_counter()
        try:
            principal = await self._authenticator.authenticate(credential)
        except TokenExpiredError:
            return await self._unauthorized(
                request,
                AuthenticationDecision.EXPIRED,
                method,
                message="Access token has expired.",
                started=started,
            )
        except AuthError:
            return await self._unauthorized(
                request,
                AuthenticationDecision.INVALID_TOKEN,
                method,
                message="Authentication failed.",
                started=started,
            )

        resolved_method = _method_for_principal(principal, method)
        context = AuthenticationContext.from_principal(
            principal, authentication_method=resolved_method
        )
        # Exactly one object on request.state — downstream reads this, nothing else.
        request.state.auth = context

        self._observe(resolved_method, AuthenticationDecision.SUCCESS, started)
        bind_request_context(
            request_id=getattr(request.state, "request_id", "unknown"),
            principal_type=context.principal_type.value,
        )
        await self._audit.record(
            AuthAuditEvent(
                action="request.authenticated",
                result=AuthenticationDecision.SUCCESS.value,
                organization_id=context.organization_id,
                principal_type=context.principal_type.value,
                subject_id=context.principal_id,
                detail=resolved_method.value,
            )
        )
        return await call_next(request)

    @staticmethod
    def _observe(
        method: AuthenticationMethod, decision: AuthenticationDecision, started: float
    ) -> None:
        """Record latency. Labels are closed vocabularies only — no ids, no messages."""
        auth_duration_seconds.labels(
            method=method.value,
            result="success" if decision.is_success else "failure",
        ).observe(time.perf_counter() - started)

    async def _unauthorized(
        self,
        request: Request,
        decision: AuthenticationDecision,
        method: AuthenticationMethod,
        *,
        message: str,
        started: float,
        code_override: str | None = None,
    ) -> JSONResponse:
        self._observe(method, decision, started)
        code = code_override or _DECISION_TO_ERROR_CODE.get(decision, "invalid_credential")
        await self._audit.record(
            AuthAuditEvent(
                action="request.rejected",
                result=decision.value,
                detail=code,
            )
        )
        body = {
            "error": {
                "type": "authentication_error",
                "code": code,
                "message": message,
                "request_id": getattr(request.state, "request_id", "unknown"),
            }
        }
        return JSONResponse(body, status_code=401)
