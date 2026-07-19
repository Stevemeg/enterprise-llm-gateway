# API Pagination, Filtering & Sorting

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Uniform list semantics across every collection. Realizes the DB pagination guidance
([`Query_Performance_Guide.md`](Query_Performance_Guide.md) §6) and keeps large lists fast at scale.

## 1. Pagination — keyset (cursor)
- Params: `cursor` (opaque) + `limit` (1–200, default 50). Response envelope:
```json
{ "data": [ /* items */ ], "page": { "has_more": true, "next_cursor": "eyJ0cyI6…", "limit": 50 } }
```
- To fetch the next page, pass `cursor=<next_cursor>`. When `has_more:false`, `next_cursor` is null.
- **Keyset, not offset:** the cursor encodes the sort key of the last row (e.g., `(created_at, id)`), so
  pages are **stable under concurrent inserts** and O(n) — no deep-offset scans. This is mandatory on
  large/append collections (`/usage`, `/audit-events`, `/api-keys`, …).
- The cursor is **opaque and signed**; clients must treat it as a black box (its internals may change
  without notice — non-breaking).
- Default ordering is `created_at DESC, id DESC` unless the endpoint documents otherwise.

## 2. Filtering
- **Explicit, documented query params per resource** — no free-form query language in v1 (predictable,
  injection-safe, index-friendly).
- Common filters: `status`, `project_id`, `provider_id`, `model_id`, `scope`, `enabled`, and time-range
  `from`/`to` (RFC 3339) on time-series endpoints (`/usage`, `/audit-events`).
- Multiple filters combine with **AND**. Repeated params (e.g., `status=a&status=b`) mean **OR within the
  field** where documented.
- Every filter maps to an **indexed** column (see [`Indexing_Strategy.md`](Indexing_Strategy.md)); unknown
  filter params → `422 validation_error`.
- Tenant scope is **implicit** (from auth) and cannot be filtered/overridden.

## 3. Sorting
- `sort=field` (asc) or `sort=-field` (desc); comma-separate for tie-breaks: `sort=-created_at,name`.
- Only **documented, indexed** sort fields are allowed; others → `422`. The primary sort field must be
  compatible with the keyset cursor (so pagination stays stable).

## 4. Aggregated listing (`/usage`)
`/usage` supports `group_by` (`day|model|project|provider`) with `from`/`to`; results are precomputed
aggregates (`usage_rollup`) for performance (FR-086). Raw records are available via `/usage/export`.

## 5. Limits & safety
- `limit` capped at 200; requests above are clamped (documented) — protects the DB and callers.
- Time-range queries on huge partitioned tables (`/usage`, `/audit-events`) should include `from`/`to`;
  unbounded ranges are limited to the online retention window.
- Export endpoints stream (CSV/JSON) rather than paginate for bulk extraction.

## 6. Consistency rules
- **Every** list endpoint uses this exact envelope + `cursor`/`limit` — no endpoint invents its own
  paging. The API linter (Phase 11) enforces bare-array responses are rejected and `page` is present.

## 7. Traceability
FR-076/077/086/115; NFR-P (bounded queries), NFR-S04/S05 (scale). Aligns with keyset guidance in
[`Query_Performance_Guide.md`](Query_Performance_Guide.md).
