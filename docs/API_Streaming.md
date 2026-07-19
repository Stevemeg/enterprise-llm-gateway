# API Streaming

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Real-time token streaming for inference and a justified position on WebSockets. Realizes FR-007
(streaming), NFR-P04 (TTFB overhead ≤20 ms), and the OpenAI-compatibility guarantee.

## 1. Inference streaming — Server-Sent Events (SSE)
- Trigger: `"stream": true` on `POST /v1/chat/completions` (or `/completions`). Response
  `Content-Type: text/event-stream`.
- **Wire format (OpenAI-compatible):** a sequence of `data: {chunk}\n\n` lines, each chunk mirroring
  `chat.completion.chunk` (incremental `delta`), terminated by a final `data: [DONE]` line.
- **Headers:** `X-Request-Id` (first flush), `X-Cache` (a cache hit returns the full response, typically
  non-streamed or as a single chunk), `Cache-Control: no-cache`, `Connection: keep-alive`.
- **Ordering & framing:** chunks are ordered; clients concatenate `delta.content`. Heartbeat comments
  (`: keep-alive`) may be sent to keep intermediaries from timing out.

### Why SSE (vs WebSocket/gRPC) for inference
| Option | Fit | Verdict |
|--------|-----|---------|
| **SSE** | One-way server→client token stream over plain HTTP; proxy/CDN-friendly; trivial client; **matches OpenAI** | **Chosen** |
| WebSocket | Bidirectional; heavier; not OpenAI-compatible; harder through corporate proxies | Rejected for inference |
| gRPC streaming | Efficient but not browser-native, not OpenAI-compatible, higher client burden | Rejected for public API |

SSE is unidirectional (server→client), which is exactly the inference streaming shape, and preserves the
drop-in OpenAI experience.

## 2. Streaming semantics & governance
- **Budget:** reservation is taken **before** the stream starts (on `max_tokens`); commit/reconcile occurs
  on stream completion from actual usage (ADR-0004). A mid-stream budget breach cannot occur because the
  reservation bounds it.
- **Failover:** provider failover happens **before first byte**; once streaming has begun, a mid-stream
  provider failure ends the stream with a terminal error event (client may retry with the same
  `Idempotency-Key`). Documented so clients handle partial streams.
- **Governance:** PII/residency are enforced pre-stream (fail closed, ADR-0009). Response logging follows
  `governance_policy` (store/hash/drop).
- **Errors before first byte** use the normal JSON `Error` body + status; **errors after streaming starts**
  are delivered as a terminal SSE event: `event: error\ndata: {Error}` then stream close.

## 3. Cancellation & timeouts
- Client disconnect (closed connection) **cancels** the upstream provider call and releases the reservation
  (no charge for unsent tokens beyond what was produced).
- Idle/overall timeouts are enforced; on timeout a terminal error event closes the stream.

## 4. WebSockets — where (and only where) justified
SSE covers inference. WebSockets are considered **only** for **admin/operational live feeds** where the
client benefits from a persistent, low-latency, possibly bidirectional channel:
- **Live usage/cost dashboards** and **live tail of audit/notifications** in the admin UI.
- **Operational monitoring** streams (e.g., real-time provider-health/routing events) for operators.

Justification: these are dashboard/monitoring experiences with many rapidly-updating small messages where
repeated polling is wasteful. If built, they are **separate, admin-authenticated (JWT/RBAC)** endpoints
(e.g., `wss://…/v1/admin/stream`), **not** part of the inference contract, and are **optional** — the same
data is always available via REST polling so no capability depends on WebSockets. This keeps the public
inference API purely SSE and proxy-friendly. A concrete WebSocket contract, if pursued, is specified in a
follow-up under an ADR (not in v1 scope).

## 5. Client guidance & SDKs
- SDKs expose streaming as an async iterator/generator yielding deltas, handling reconnection and terminal
  events ([`API_SDK_Guidelines.md`](API_SDK_Guidelines.md)).
- Recommend HTTP/2 for multiplexing many concurrent streams; ensure intermediaries don't buffer
  `text/event-stream`.

## 6. Traceability
FR-007, NFR-P04; ADR-0004 (reservation over stream), ADR-0003/0012 (pre-stream failover), ADR-0009
(pre-stream governance). Sequence: [`architecture/sequence/01-inference-cache-miss.md`](architecture/sequence/01-inference-cache-miss.md).
