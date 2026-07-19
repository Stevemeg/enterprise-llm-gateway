# API Authentication & Authorization

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

How callers authenticate and how requests are authorized. Realizes ADR-0008 (auth/RBAC/keys), ADR-0002
(tenant scoping), ADR-0009 (fail closed). Schemas/flows: `securitySchemes` in
[`api/OpenAPI.yaml`](api/OpenAPI.yaml).

## 1. Two principal types
| Principal | Credential | Used for | Scheme |
|-----------|-----------|----------|--------|
| **Application** | Virtual **API key** (`Authorization: Bearer elg_live_…`) | Inference (`/v1/chat/completions`, …) | `apiKey` (HTTP bearer) |
| **Human admin / service account** | **OIDC → gateway JWT** (`Authorization: Bearer <jwt>`) | Admin/control-plane | `oidcJwt` (OAuth2 auth-code) |

The **tenant (organization) is always derived from the credential**, never from a request field — this
underpins tenant isolation (ADR-0002) and prevents cross-tenant access by construction.

## 2. Virtual API keys (inference) — FR-094..097
- Presented as `Authorization: Bearer <key>`. Format `elg_<env>_<random>`; only a **SHA-256 hash** is
  stored (`api_key.key_hash`); the full secret is shown **once** at creation (`ApiKeyCreated.secret`).
- Keys carry **scopes** (`infer:chat`, `infer:embed`) — a chat-only key used on `/v1/embeddings` →
  `403 insufficient_scope`.
- **Rotation** (`POST /api-keys/{id}/rotate`) issues a new secret; **revocation** (`DELETE`) is immediate.
  Keys may have `expires_at`.
- Validation is O(1) by hash lookup on the hot path; result cached briefly (see
  [`Query_Performance_Guide.md`](Query_Performance_Guide.md)). Failure **fails closed** (401).

## 3. Admin auth: OIDC + JWT — FR-090..093
- **Flow:** OAuth2 **authorization-code + PKCE** against the enterprise IdP (Okta/Azure AD/Google). The
  gateway exchanges the code (`POST /v1/auth/token`) for a **short-lived access JWT** + **rotating refresh
  token** (`POST /v1/auth/refresh`); `POST /v1/auth/logout` revokes the session.
- **JWT** carries `sub`, `org` (tenant), `roles`, `exp`; signed by the gateway and validated via JWKS.
  Signing keys **rotate** with revocation (FR-093). Refresh tokens are stored **hashed** and rotate on use
  (reuse detection → revoke chain).
- Access-token TTL is short (minutes); refresh TTL longer (configurable). Expired token → `401
  token_expired`.

## 4. Authorization (RBAC) — FR-098..101
- Every admin operation is checked by the central **`AuthorizationPort`** decision function (same logic in
  API and UI, FR-128): *does the principal's role, within the resource's tenant/project scope, grant the
  required permission?*
- **Deny-by-default, least privilege** (FR-099/100). Roles: `owner, admin, operator, finance, auditor,
  developer` → fine-grained permissions (ADR-0008 matrix). Example: `auditor` calling
  `PATCH /budgets/{id}` → `403 permission_error`; the denied attempt is **audited** (FR-101).
- Virtual-key **scopes** are an inference-only subset and never grant admin permissions.

### Endpoint → permission (representative)
| Operation | Permission |
|-----------|-----------|
| `POST /budgets`, `PATCH /budgets/{id}` | `budget:write` |
| `GET /budgets`, `GET /usage` | `budget:read` / `usage:read` |
| `POST /api-keys`, `/rotate`, `DELETE` | `key:issue` / `key:revoke` |
| `POST/PATCH /providers`, `/admin/models` | `provider:write` / `model:write` |
| `POST/PATCH /routing-policies` | `routing:write` |
| `GET /audit-events` | `audit:read` |
| `POST /roles`, `/memberships` | `rbac:write` |
| `POST/PATCH /governance*` | `governance:write` |

## 5. Security headers & transport
- **TLS 1.2+** required (NFR-SEC01); non-TLS refused.
- Standard security headers on responses (`Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
  etc.) — see [`API_Governance.md`](API_Governance.md).
- **CORS:** admin API allows the dashboard origin(s) only; inference API is server-to-server (no
  browser-embedded keys recommended).

## 6. Failure semantics (fail closed — ADR-0009)
| Condition | Result |
|-----------|--------|
| No/invalid credential | `401 authentication_error` |
| Valid principal, missing permission/scope | `403 permission_error` / `insufficient_scope` |
| IdP/JWKS unreachable | `401` (cannot verify → deny) |
| Key store unavailable | `401` (cannot validate → deny) |
| Tenant context unresolved | deny (no rows; RLS deny-by-default) |

## 7. Auditing
All authentication outcomes for sensitive actions and **every** authorization decision on mutating admin
calls are written to the immutable audit log (FR-101/113), queryable via `GET /audit-events`.

## 8. Traceability
FR-090..101, FR-128/129, ADR-0002/0008/0009; NFR-SEC01/04/05/09. See
[`RLS_Strategy.md`](RLS_Strategy.md) for the DB-enforced tenant backstop and
[`architecture/sequence/05-auth-oidc-rbac.md`](architecture/sequence/05-auth-oidc-rbac.md) for the flow.
