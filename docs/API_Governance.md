# API Governance

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

The rules that keep the API consistent, reviewable, and machine-generatable across 87 operations and all
future additions. Enforced by design review + an automated **API linter** (Spectral or equivalent) in CI
(Phase 11). Complements [`API_Design_Guide.md`](API_Design_Guide.md).

## 1. Naming standards
- **Paths:** lowercase, hyphenated, **plural** nouns (`/routing-policies`, `/api-keys`). No verbs in
  collection paths; non-CRUD actions are explicit sub-paths (`/api-keys/{id}/rotate`).
- **Path params:** `{resource_id}` snake_case, UUID unless the resource is natural-keyed (`{model_id}` may
  be a model name on the OpenAI-compatible surface).
- **Query params:** snake_case (`project_id`, `group_by`, `from`, `to`).
- **Fields:** snake_case, matching DB/OpenAI conventions.
- **operationId:** `camelCase`, `verbResource` (`createBudget`, `listApiKeys`, `rotateApiKey`) — unique
  across the spec (drives SDK method names).
- **Enums:** lowercase snake_case values, mirroring the DB enums.
- **Error codes/types:** as in [`API_Error_Model.md`](API_Error_Model.md).

## 2. Resource conventions
- Collections return an **envelope** `{ data: [...], page: {...} }` — never a bare array.
- Create → `201` + `Location` + representation. Update → `PATCH` (partial) returns the full resource.
  Replace of config/flags → `PUT`. Delete/revoke → `204`; async delete → `202`.
- Sub-resources model containment (`/prompt-templates/{id}/versions`).
- Secrets are **write-once/reference-only**: `ApiKeyCreated.secret` appears once; provider/webhook secrets
  are `*_secret_ref` UUIDs (ADR-0011). No endpoint ever returns a stored secret value.

## 3. URI design rules
- Stable, hierarchical, tenant-implicit (no org id in path).
- Version prefix `/v1` on all business endpoints; ops endpoints (`/healthz`, `/metrics`) are unversioned.
- Idempotent, cacheable GETs; mutations never in GET.

## 4. Request consistency
- JSON bodies; `Content-Type: application/json` required on write.
- Mutating POSTs accept `Idempotency-Key`.
- Inputs validated against schema; unknown fields rejected where schemas are strict; validation failures →
  `422` with `details[]`.
- No credentials, tenant ids, or ambient authority in the body — derived from the token/key.

## 5. Response consistency
- Always include `X-Request-Id`. Inference includes `X-Cache`. Lists include `page`. Money includes
  `currency`. Timestamps are RFC 3339 UTC.
- Same resource shape on create/read/list (list may omit heavy fields, documented).
- Errors always use the `Error` envelope.

## 6. Error consistency
Single model, stable codes, one type + one HTTP status per code, correlation id, retry guidance, doc link
— see [`API_Error_Model.md`](API_Error_Model.md). Linter checks every operation declares the standard
error responses appropriate to it.

## 7. Security headers (responses)
| Header | Value/purpose |
|--------|---------------|
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` (TLS enforcement, NFR-SEC01) |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` / CSP | clickjacking protection for the dashboard |
| `Cache-Control` | `no-store` on auth/secret-bearing responses |
| `Content-Type` | explicit, correct per body |
CORS restricted to known dashboard origins on admin API; inference is server-to-server.

## 8. Tracing & correlation headers
| Header | Direction | Purpose |
|--------|-----------|---------|
| `X-Request-Id` | req (optional) / resp (always) | Client-supplied or server-generated correlation id (FR-080) |
| `traceparent` (+ `tracestate`) | req/resp | W3C trace context propagation (FR-083) |
| `Idempotency-Key` | req | Safe retries (mutations) |
| `RateLimit` / `Retry-After` | resp | Rate-limit state (FR-065) |
| `Deprecation` / `Sunset` | resp | Lifecycle signaling ([`API_Deprecation_Policy.md`](API_Deprecation_Policy.md)) |

Every request is traceable end-to-end by `X-Request-Id` across logs, metrics, and traces (FR-080/082/083).

## 9. Correlation IDs
- Format: `req_` + a time-ordered token. Echoed in `X-Request-Id` and `error.request_id`.
- Propagated into provider calls and events so a single id links gateway → routing → provider → metering.

## 10. Linting & enforcement (CI, Phase 11)
Automated ruleset checks: path/param/field casing, plural collections, `operationId` presence+uniqueness,
every operation has `tags`+`responses`+standard errors, no bare-array responses, security defined per
operation, examples present on key operations, and no secret-returning fields except the documented
one-time key. Violations fail the build (NFR-M05/M06).

## 11. Traceability
FR-009/010/065/080/083/128/129, ADR-0002/0008/0009/0011, NFR-SEC01/05/08, NFR-M05/M06.
