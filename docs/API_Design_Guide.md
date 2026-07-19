# API Design Guide

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Principles and conventions for the public + admin API. The machine-readable contract is
[`api/OpenAPI.yaml`](api/OpenAPI.yaml); this guide explains the *why* and the rules every endpoint
follows. Realizes ADR-0001/0003/0004/0008/0009/0012.

## 1. API surfaces
| Surface | Base | Auth | Purpose |
|---------|------|------|---------|
| **Inference** | `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings`, `/v1/models` | Virtual API key | OpenAI-compatible model calls (FR-001..010) |
| **Admin / control plane** | `/v1/organizations`, `/v1/providers`, `/v1/budgets`, … | OIDC/JWT + RBAC | Configuration & governance |
| **Ops** | `/healthz`, `/readyz`, `/livez`, `/metrics` | None (network-restricted) | Operability (NFR-O03) |

## 2. Design tenets
- **OpenAI-compatible where it counts.** Inference request/response shapes mirror OpenAI so migration
  is base-URL + key only (AC-US-001). Gateway extras live under an additive `x_gateway` object — never
  breaking the OpenAI shape.
- **Resource-oriented REST.** Nouns, plural collections, sub-resources for containment. Standard verbs.
- **Consistency over cleverness.** Every list paginates the same way, every error looks the same, every
  mutating POST accepts `Idempotency-Key`.
- **Least privilege & tenant isolation by default.** Every admin call is RBAC-checked and tenant-scoped
  (ADR-0002/0008); the tenant is derived from the token/key, never a request field.
- **Fail closed on integrity, degrade on enrichment** (ADR-0009) — reflected in status codes (402/403/
  503 vs. cache-miss fallthrough).

## 3. URI & resource conventions
- Lowercase, hyphenated, **plural** collection names: `/routing-policies`, `/api-keys`, `/service-accounts`.
- Resource by id: `/projects/{project_id}` (UUID). Sub-resources express containment:
  `/prompt-templates/{id}/versions`, `/webhooks/{id}/deliveries`, `/providers/{id}/health`.
- Actions that aren't CRUD use a **verb sub-path**: `/api-keys/{id}/rotate`, `/cache/entries` (DELETE = purge).
- No trailing slashes; no verbs in collection names; no tenant id in the path (implicit from auth).
- Admin-only registry mutations that could collide with the OpenAI-compatible `/models` read live under
  `/admin/models` to keep the public `/models` OpenAI-shaped.

## 4. HTTP methods & status codes
| Method | Use | Success |
|--------|-----|---------|
| GET | read/list | 200 |
| POST | create / action | 201 (create, `Location`), 200/202 (action), 200 (inference) |
| PATCH | partial update | 200 |
| PUT | idempotent replace (config/flags) | 200 |
| DELETE | remove/revoke/purge | 204 (no body) / 202 (async) |

Error codes: 400 malformed, 401 unauthenticated, 402 budget exceeded, 403 authz denied, 404 not found,
409 conflict, 422 validation, 429 rate/quota, 5xx server, 502 provider, 503 no-provider/not-ready.
Full model: [`API_Error_Model.md`](API_Error_Model.md).

## 5. Request & response consistency
- **JSON** (`application/json`) everywhere except SSE (`text/event-stream`) and `/metrics` (text) and
  CSV export.
- **snake_case** field names (matches DB/OpenAI; consistent across the API).
- Timestamps are **RFC 3339 / ISO-8601 UTC** (`created_at`). Money is a JSON number in the account
  currency with an explicit `currency` field.
- **Create** returns `201` + `Location` + the created resource. **List** returns `{ data: [...], page: {...} }`
  (envelope) — never a bare array (extensible, paginatable).
- Unknown request fields are rejected on strict schemas (`additionalProperties:false` on the error
  model; documented per resource) to catch client mistakes early.
- Responses never leak other tenants' data, provider credentials, or stack traces (FR-010).

## 6. Idempotency, pagination, filtering, sorting
- **Idempotency:** all create/action POSTs accept `Idempotency-Key` (24h replay) —
  [`API_Idempotency.md`](API_Idempotency.md).
- **Pagination:** opaque **keyset** cursor (`cursor`,`limit`) — [`API_Pagination_Filtering.md`](API_Pagination_Filtering.md).
- **Filtering:** explicit query params per resource (`status`, `project_id`, `from`/`to`, …) — no
  free-form query language in v1.
- **Sorting:** `sort=field` / `sort=-field` (desc) on documented fields.

## 7. Headers (see [`API_Governance.md`](API_Governance.md))
- **Request:** `Authorization` (Bearer), `Idempotency-Key`, `X-Request-Id` (optional), `traceparent`
  (W3C, FR-083).
- **Response:** `X-Request-Id` (always), `X-Cache` (inference), `RateLimit`/`Retry-After`, `Location`
  (creates), standard security headers.

## 8. Compatibility & versioning
- URL-versioned at `/v1`; **additive changes only** within a version; breaking changes → `/v2`. See
  [`API_Versioning_Strategy.md`](API_Versioning_Strategy.md) and
  [`API_Deprecation_Policy.md`](API_Deprecation_Policy.md).
- Gateway-specific additions ride in `x_gateway` / `x-` extensions so OpenAI compatibility is stable.

## 9. Streaming
Inference streaming uses **SSE** (`stream:true`). WebSockets are considered only for admin/monitoring
live feeds and justified separately — [`API_Streaming.md`](API_Streaming.md).

## 10. Governance & SDKs
Naming, header, and consistency rules are enforced per [`API_Governance.md`](API_Governance.md); SDK
generation from the OpenAPI spec is covered in [`API_SDK_Guidelines.md`](API_SDK_Guidelines.md).
