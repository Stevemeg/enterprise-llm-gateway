"""Request-body size limiting (Phase 5 M3, Phase-4 review §4.5).

An LLM gateway's request body is the one input a caller controls the size of, and every stage
downstream is proportional to it: FastAPI buffers and parses it, ``LocalPolicyEngine`` measures it,
``compute_cache_key`` canonicalizes and SHA-256s it, and ``OpenAiCompatibleProviderClient`` ships
it upstream. Before this milestone the only bound on ``prompt`` was ``min_length=1``.

## Why this is raw ASGI rather than a ``BaseHTTPMiddleware``

``BaseHTTPMiddleware.dispatch`` receives a ``Request`` whose body it can only inspect by *reading*
it, which then has to be replayed for the route, and whose ``call_next`` runs the rest of the app
inside an ``anyio`` task group. Both matter here: the check has to sit on the ``receive`` channel
itself, and it must not have its failure repackaged on the way out.

## Two paths, because a client may not declare its size

**1. ``Content-Length`` present.** Over the cap, the request is refused before the app is called at
all - not one byte of the body is read. At or under the cap, the request is passed through
completely untouched: no wrapping, no buffering, no copy. This is the path every ordinary HTTP
client takes, and it costs nothing. Trusting the declared value *as an upper bound* is safe
because it has already been checked and because the ASGI server enforces it - a client that
declares 10 bytes cannot deliver 4096, the server truncates at the declared length.

**2. No usable ``Content-Length``** (chunked transfer, or an unparseable header). Here the running
byte count is the only bound, and it is read **eagerly, up to the cap**, before the app is called:
the body is accumulated message by message and the request is refused the instant the total
crosses the limit, at which point reading stops. A body that fits is then replayed to the app from
the buffer.

An unparseable ``Content-Length`` is deliberately treated as *absent* rather than rejected outright.
Rejecting it would duplicate protocol validation the ASGI server already owns; routing it into the
counting path bounds it just as tightly without this middleware inventing an opinion about HTTP
syntax.

### Why eager reading rather than counting as the route reads

The obvious design - wrap ``receive``, raise when the count is exceeded, answer 413 from the
handler - **does not work, and fails silently rather than loudly.** FastAPI's request handler wraps
its ``await request.body()`` in a bare ``except Exception`` and re-raises it as
``HTTPException(400, "There was an error parsing the body")``. The 413 would therefore never be
produced: the caller would get FastAPI's generic 400, the ``API_Error_Model.md`` envelope would be
absent, and the limit would look enforced while reporting the wrong thing. Verified against this
repository's own stack before choosing the alternative, not assumed.

Reading first costs a buffer, and the bound on that buffer is the point: at most ``max_bytes`` plus
the one server read-chunk that crossed the line, after which nothing further is read. That is
strictly less than the route would have buffered anyway, and it is the only shape in which the
count can be turned into a correct response.

## Placement: outside authentication, inside request context

Outside authentication because the check needs no identity and authentication is not free - the
API-key path performs a database lookup, so reading a body in order to then reject it as
unauthenticated would be strictly worse than refusing it on arrival. Inside request context so the
``413`` still carries its ``X-Request-Id`` and appears in the access log like every other response.

The cap is a deployment-wide constant, identical for every caller and independent of tenant, so a
``413`` before authentication discloses nothing that is not already a fixed property of the
deployment - the same reasoning that makes ``client_max_body_size`` a pre-auth check in every
reverse proxy.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gateway.observability.metrics import (
    INGRESS_BODY_SIZE,
    INGRESS_DENIED,
    record_ingress_decision,
)


def _declared_length(scope: Scope) -> int | None:
    """The client's declared body size, or ``None`` when absent or unparseable."""
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _too_large_response(scope: Scope, max_bytes: int) -> JSONResponse:
    """``API_Error_Model.md``'s envelope for a refused body.

    ``retryable`` is **false**: the body will be the same size next time, so retrying is guaranteed
    to fail. The message states the cap because it is a fixed, public property of the deployment
    and a client that does not learn it can only guess; it names nothing tenant-specific.
    """
    request_id = scope.get("state", {}).get("request_id", "unknown")
    return JSONResponse(
        {
            "error": {
                "type": "invalid_request_error",
                "code": "request_too_large",
                "message": f"Request body exceeds the maximum of {max_bytes} bytes.",
                "request_id": request_id,
                "retryable": False,
            }
        },
        status_code=413,
    )


def _replaying_receive(buffered: list[Message], receive: Receive) -> Receive:
    """Hand the app the messages already consumed, then defer to the real channel.

    The tail matters: ``http.disconnect`` can arrive after the body is complete, and an app that
    stopped receiving at the end of the buffer would never learn the client had gone.
    """
    pending = list(buffered)

    async def replay() -> Message:
        if pending:
            return pending.pop(0)
        return await receive()

    return replay


class RequestSizeLimitMiddleware:
    """Refuses a request whose body exceeds ``max_bytes``, before it is parsed or routed."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError(
                f"max_bytes must be >= 1, got {max_bytes}; a non-positive cap would refuse "
                "every request that carries a body at all"
            )
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Lifespan and websocket scopes carry no HTTP body; passing them through untouched
            # keeps this middleware from having an opinion about protocols it does not police.
            await self._app(scope, receive, send)
            return

        declared = _declared_length(scope)
        if declared is not None:
            if declared > self._max_bytes:
                await self._refuse(scope, receive, send)
                return
            # Declared and within the cap: the server will not deliver more than it declared, so
            # there is nothing left to enforce. Pass through with zero overhead.
            await self._app(scope, receive, send)
            return

        buffered: list[Message] = []
        received = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":
                # A disconnect before the body finished. Nothing to police; let the app see it.
                break
            received += len(message.get("body", b""))
            if received > self._max_bytes:
                # Stop reading here. This is the bound: nothing beyond the cap (plus the chunk
                # that crossed it) is ever held.
                await self._refuse(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        await self._app(scope, _replaying_receive(buffered, receive), send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        record_ingress_decision(control=INGRESS_BODY_SIZE, outcome=INGRESS_DENIED)
        await _too_large_response(scope, self._max_bytes)(scope, receive, send)
