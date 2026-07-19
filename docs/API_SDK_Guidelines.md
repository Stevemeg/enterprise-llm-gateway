# API SDK Guidelines

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Guidance for official SDKs (Python, TypeScript, Go, Java) and for generating them from
[`api/OpenAPI.yaml`](api/OpenAPI.yaml). Goal: idiomatic, typed, resilient clients that stay in lockstep
with the contract.

## 1. Generation strategy
- **Source of truth:** the OpenAPI 3.1 spec. SDKs are **generated** (openapi-generator / language-native
  generators) then wrapped with a thin hand-written ergonomic layer (auth, retries, streaming, pagination
  helpers). This keeps models/endpoints in sync automatically while allowing idiomatic UX.
- **CI regeneration:** on every spec change, regenerate and diff; breaking diffs gate the release
  ([`API_Versioning_Strategy.md`](API_Versioning_Strategy.md)).
- **operationId → method name** (`createChatCompletion` → `client.chat.completions.create`), so the spec's
  naming governance ([`API_Governance.md`](API_Governance.md)) directly shapes SDK ergonomics.
- **Tags → namespaces** (e.g., `client.budgets`, `client.providers`).

## 2. Cross-language requirements (all SDKs)
- **Auth:** accept a virtual key (inference) or admin token; set `Authorization: Bearer`. Never log
  secrets.
- **OpenAI-compatibility:** the inference surface mirrors the OpenAI SDK shape so users can swap base URL +
  key (AC-US-001).
- **Retries:** automatic exponential backoff + jitter on `429`/`502`/`503`, honoring `Retry-After`; reuse
  the same `Idempotency-Key` across retries of one logical call ([`API_Idempotency.md`](API_Idempotency.md)).
- **Idempotency:** auto-attach a UUID `Idempotency-Key` to create/action calls.
- **Pagination:** expose auto-paging iterators that follow `page.next_cursor`
  ([`API_Pagination_Filtering.md`](API_Pagination_Filtering.md)).
- **Streaming:** expose SSE as a native async stream/iterator yielding deltas, with terminal-event and
  cancellation handling ([`API_Streaming.md`](API_Streaming.md)).
- **Errors:** map the `Error` envelope to typed exceptions per `type`/`code`; expose `request_id`,
  `retryable`, `retry_after_seconds`, `doc_url`.
- **Forward-compat:** ignore unknown response fields and unknown output-enum values (never crash) —
  required by [`API_Versioning_Strategy.md`](API_Versioning_Strategy.md).
- **Tracing:** propagate/accept `traceparent`; surface/attach `X-Request-Id`.
- **Config:** base URL override (for self-host), timeouts, proxy, custom headers.

## 3. Per-language notes
### Python
- Async-first (`httpx`), sync wrapper provided. Streaming via `async for chunk in client.chat.completions.stream(...)`.
- Pydantic models generated from schemas; type hints throughout. Mirrors the OpenAI Python SDK ergonomics.

### TypeScript
- Isomorphic (Node + browser-safe for admin; inference keys server-side only). ESM + types from spec.
- `for await (const chunk of stream)` for SSE; discriminated-union error types by `error.type`.

### Go
- Context-aware (`ctx` first arg), typed structs, `errors.As` for typed API errors. Channels/iterators for
  streaming. Functional options for client config.

### Java
- Builder-pattern client; `CompletableFuture`/reactive streaming option; typed exception hierarchy. Jackson
  models tolerant of unknown fields (`FAIL_ON_UNKNOWN_PROPERTIES=false`).

## 4. Versioning & release
- SDK version is independent but declares the API **major** it targets. Minor API additions → minor SDK
  release; breaking API (`/v2`) → new SDK major with a migration guide.
- Changelogs generated from the spec diff + [`API_Changelog_Policy.md`](API_Changelog_Policy.md).

## 5. Quality bar
- Generated + wrapper code passes lint/type checks; examples in [`API_Examples.md`](API_Examples.md) are
  compiled/tested as SDK snippets (Phase 13).
- Contract tests run each SDK against a mock server derived from the spec
  ([`API_Testing_Strategy.md`](API_Testing_Strategy.md)).

## 6. Traceability
FR-001..010 (inference parity), NFR-M06 (documented interfaces), NFR-UX02 (actionable errors); supports
Personas P-04 (developers) and P-01 (platform).
