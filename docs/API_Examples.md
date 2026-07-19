# API Examples

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Representative request/response examples across surfaces. These mirror
[`api/OpenAPI.yaml`](api/OpenAPI.yaml) and are compiled/tested as fixtures/SDK snippets in Phase 13.
Values are illustrative; ids abbreviated.

## 1. Chat completion (non-streaming)
**Request**
```http
POST /v1/chat/completions
Authorization: Bearer elg_live_ab12…
Idempotency-Key: 6f1c… 
Content-Type: application/json

{ "model": "gpt-4o", "messages": [ { "role": "user", "content": "Summarize CAP theorem in one line." } ], "max_tokens": 60 }
```
**Response `200`**
```http
X-Request-Id: req_01HZY…
X-Cache: miss
RateLimit: limit=1000, remaining=994, reset=27

{ "id": "chatcmpl_…", "object": "chat.completion", "model": "gpt-4o",
  "choices": [ { "index": 0, "message": { "role": "assistant", "content": "You can have at most two of consistency, availability, and partition tolerance." }, "finish_reason": "stop" } ],
  "usage": { "prompt_tokens": 18, "completion_tokens": 16, "total_tokens": 34, "cost": 0.00042 },
  "x_gateway": { "request_id": "req_01HZY…", "cache": "miss", "selected_provider": "openai", "selected_model": "gpt-4o", "failover_count": 0 } }
```

## 2. Chat completion (streaming, SSE)
**Request:** same as above with `"stream": true`.
**Response `200` (`text/event-stream`)**
```
data: {"id":"chatcmpl_…","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant"}}]}

data: {"id":"chatcmpl_…","object":"chat.completion.chunk","choices":[{"delta":{"content":"You "}}]}

data: {"id":"chatcmpl_…","object":"chat.completion.chunk","choices":[{"delta":{"content":"can…"}}]}

data: [DONE]
```
Mid-stream error (after first byte):
```
event: error
data: {"error":{"type":"provider_error","code":"provider_unavailable","message":"Upstream ended the stream.","request_id":"req_01HZY…","retryable":true}}
```

## 3. Embeddings
```http
POST /v1/embeddings
Authorization: Bearer elg_live_…
{ "model": "text-embedding-3-large", "input": ["invoice overdue", "payment reminder"] }
```
```json
{ "object": "list", "model": "text-embedding-3-large",
  "data": [ { "object": "embedding", "index": 0, "embedding": [0.0123, -0.0456, "…"] } ],
  "usage": { "prompt_tokens": 6, "completion_tokens": 0, "total_tokens": 6, "cost": 0.0000012 } }
```

## 4. Budget exceeded (`402`)
```json
{ "error": { "type": "budget_error", "code": "budget_exceeded",
  "message": "Monthly budget for project 'search' is exhausted.",
  "request_id": "req_01HZZ…", "retryable": false,
  "doc_url": "https://docs.example.com/errors/budget_exceeded" } }
```

## 5. Insufficient scope (`403`)
Chat-only key calling `/v1/embeddings`:
```json
{ "error": { "type": "permission_error", "code": "insufficient_scope",
  "message": "This API key lacks the 'infer:embed' scope.", "request_id": "req_…", "retryable": false } }
```

## 6. Create a hard budget (admin)
```http
POST /v1/budgets
Authorization: Bearer <admin-jwt>
Idempotency-Key: 9a2e…

{ "scope": "project", "scope_id": "proj_…", "period": "monthly", "limit_kind": "hard",
  "amount_limit": 5000, "currency": "USD",
  "period_start": "2026-08-01T00:00:00Z", "period_end": "2026-09-01T00:00:00Z",
  "alert_thresholds": [80, 100] }
```
```http
201 Created
Location: /v1/budgets/bud_…

{ "id": "bud_…", "scope": "project", "scope_id": "proj_…", "amount_limit": 5000,
  "consumed_amount": 0, "limit_kind": "hard", "is_active": true, "period_start": "…", "period_end": "…" }
```

## 7. Issue a virtual key (secret shown once)
```http
POST /v1/api-keys
{ "name": "search-service", "project_id": "proj_…", "scopes": ["infer:chat", "infer:embed"] }
```
```json
{ "id": "key_…", "name": "search-service", "key_prefix": "elg_live_ab12",
  "scopes": ["infer:chat","infer:embed"], "status": "active",
  "secret": "elg_live_ab12cd34…ONLY_SHOWN_NOW" }
```

## 8. Create a routing policy (cost-first with fallback)
```http
POST /v1/routing-policies
{ "name": "default-cost", "strategy": "lowest_cost",
  "constraints": { "allowed_regions": ["us-east-1","us-west-2"] },
  "rules": [ { "priority": 1, "model_id": "mdl_cheap" }, { "priority": 2, "model_id": "mdl_premium" } ] }
```

## 9. Paginated list (keyset)
```http
GET /v1/api-keys?limit=2
```
```json
{ "data": [ { "id": "key_1", "…": "…" }, { "id": "key_2", "…": "…" } ],
  "page": { "has_more": true, "next_cursor": "eyJ0cyI6IjIwMjYtMDctMTUiLCJpZCI6ImtleV8yIn0", "limit": 2 } }
```
Next page: `GET /v1/api-keys?limit=2&cursor=eyJ0cyI6…`

## 10. Usage query (aggregated)
```http
GET /v1/usage?from=2026-07-01T00:00:00Z&to=2026-07-31T23:59:59Z&group_by=model
```
```json
{ "data": [ { "bucket": "gpt-4o", "request_count": 120345, "total_tokens": 48200000, "total_cost": 612.44, "cache_hit_count": 51200 } ],
  "page": { "has_more": false, "next_cursor": null, "limit": 50 } }
```

## 11. Webhook delivery (signed)
```http
POST https://customer.example.com/hooks/elg
X-ELG-Signature: t=1789000000, v1=6b3f…
{ "id": "evt_…", "type": "budget.threshold_reached", "version": "1",
  "created_at": "2026-07-15T12:00:00Z", "organization_id": "org_…",
  "data": { "budget_id": "bud_…", "scope": "project", "percent": 80 } }
```

## 12. Health
```http
GET /healthz
```
```json
{ "status": "ok", "version": "1.0.0", "checks": [ { "name": "postgres", "status": "ok" }, { "name": "redis", "status": "ok" } ] }
```

More scenarios (failover, semantic-cache hit, residency block) are covered as tests in
[`API_Testing_Strategy.md`](API_Testing_Strategy.md).
