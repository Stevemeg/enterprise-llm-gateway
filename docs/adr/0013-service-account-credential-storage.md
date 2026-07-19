# ADR-0013: Service-account credential storage

- **Status:** Proposed (schema change — awaiting approval)
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Security Architect, Database Architect
- **Phase:** 5 — Backend (Milestone 3d)
- **Supersedes/affects:** extends the Phase-3 schema (adds one table)

## Context & problem
Authentication design (ADR-0008, [Authentication_Architecture.md](../Authentication_Architecture.md) §8)
specifies that **service accounts authenticate via client credentials** (`client_id` + secret) and
receive a short access token. However, the approved Phase-3 `service_account` table stores only
identity (`id, organization_id, name, description, is_active, timestamps`) — **no credential material**.

The current schema therefore **cannot securely support client-credential authentication**: there is no
column to hold a verifiable secret. Storing a client secret requires (a) a **hash** (never the plaintext,
NFR-SEC03), (b) a **stable client_id** for lookup, (c) **rotation** support (ideally with a grace window
so rotating a secret doesn't cause an outage), and (d) **status/expiry** so a compromised credential can
be revoked immediately. None of this exists today. Inventing it silently in code would be an undocumented
architectural change — hence this ADR.

## Decision drivers
- FR-098 (service accounts), FR-097 (hashed secret storage, show-once), FR-093/096 (rotation/revocation).
- NFR-SEC03 (no recoverable secret stored), NFR-SEC04 (constant-time verify), NFR-SEC05 (revocation),
  ADR-0002 (tenant isolation + RLS), ADR-0008 (auth model), ADR-0011 (secret handling).

## Options considered
### Option A — Add `client_id` + `secret_hash` columns to `service_account`
- **Pros:** Minimal change; one table.
- **Cons:** Only one credential per account; **rotation replaces the hash in place** → no grace overlap
  (brief outage on every rotation); couples identity lifecycle with credential lifecycle; no per-credential
  expiry/status without more columns. Weakest on rotation and separation of concerns.

### Option B — New `service_account_credential` table (1→many from `service_account`)
Columns: `id, organization_id, service_account_id, client_id (unique), secret_hash, status, expires_at,
created_at, rotated_at`.
- **Pros:** Supports **multiple/rotating credentials** per account with a **grace window** (issue new →
  both valid → revoke old); **independent lifecycle** (status/expiry/revoke per credential); **mirrors the
  proven `api_key` pattern** (hash + status + rotation) and the API-key state machine; clean separation of
  identity from credentials; RLS-scoped like every tenant table.
- **Cons:** One additional table (small, well-understood).

### Option C — Reuse `api_key` for service accounts
- **Pros:** No new table.
- **Cons:** `api_key` is **inference-scoped** (scopes `infer:*`, tied to `project`) and issues *virtual
  keys*, not the *client-credentials → JWT* grant service accounts use. Overloading it would require an
  owner-type discriminator + broader scopes, **muddying two distinct credential semantics** (application
  inference keys vs. machine client credentials) and weakening the api_key model's guarantees. Rejected.

## Decision
Adopt **Option B — a dedicated `service_account_credential` table.** It mirrors the reviewed `api_key`
credential pattern (SHA-256 hash, `status`, rotation), supports rotation with a grace overlap (no outage),
keeps identity and credential lifecycles separate, and is tenant-scoped with RLS. Only the **hash** is
stored (NFR-SEC03); the full secret is shown once at issuance (FR-097); verification is constant-time
(NFR-SEC04); revocation is immediate via `status`.

**Schema (added):**
```
service_account_credential(
  id uuid pk,
  organization_id uuid not null -> organization  (RLS),
  service_account_id uuid not null -> service_account,
  client_id text not null unique,
  secret_hash bytea not null,             -- SHA-256, never plaintext
  status api_key_status not null default 'active',   -- reuse active|revoked|expired
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  rotated_at timestamptz
)
```
**Lifecycle/audit fields** (added for audit trails, security investigations, compliance, and
automated rotation): `created_at`, `updated_at`, `last_used_at`, `last_rotated_at`, `expires_at`,
`revoked_at`, `rotation_reason`, `created_by`, `revoked_by`.

Applied via **Alembic migration `0002_service_account_credential`** (forward-only). `Schema.sql` (the
current-state reference) is updated to include it; the `0001` snapshot is unchanged (migration history).

## Consequences
- **Positive:** Secure, rotatable service-account authentication; consistent with api_key; RLS-isolated;
  no outage on rotation.
- **Negative:** One more table + repository to implement/test (Milestone 3d-2).
- **Follow-ups:** 3d-2 implements the SQLAlchemy repository + wires `AuthenticateServiceAccount` to it;
  the OpenAPI gains credential-issuance endpoints; the API-key state machine applies to these credentials.

## Requirements satisfied
- Functional: FR-098, FR-097, FR-093, FR-096.
- Non-functional: NFR-SEC03, NFR-SEC04, NFR-SEC05, and ADR-0002 (RLS), ADR-0008, ADR-0011.

## Review notes
Revisit only if a customer requires an external/mTLS machine-identity (e.g., SPIFFE) instead of client
secrets — that would be a new credential type behind the same account, added as a further ADR.
