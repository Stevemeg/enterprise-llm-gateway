# Sequence — Admin authentication (OIDC) + RBAC authorization

Human admin logs in via corporate SSO and performs a guarded action; virtual-key path shown for
contrast. Back to [index](README.md) · [ADR-0008](../../adr/0008-rbac-model.md).

```mermaid
sequenceDiagram
    autonumber
    participant Adm as Admin (browser/UI)
    participant UI as Dashboard (Next.js)
    participant IdP as OIDC IdP
    participant AAPI as Admin API
    participant AuthZ as AuthorizationPort (decision fn)
    participant Audit as Audit (event → immutable log)
    participant PG as PostgreSQL

    Adm->>UI: Sign in
    UI->>IdP: OIDC auth code flow
    IdP-->>UI: id_token / code
    UI->>AAPI: exchange → session; AAPI validates via JWKS
    AAPI-->>UI: gateway JWT (sub, tenant, roles; short-lived + refresh)
    Adm->>UI: "Update team budget"
    UI->>AAPI: PATCH /budgets (JWT)
    AAPI->>AuthZ: allowed(principal, tenant/team scope, perm=budget:write)?
    alt granted (owner/admin/finance)
        AuthZ-->>AAPI: permit
        AAPI->>PG: update budget (tenant-scoped, RLS)
        AAPI-)Audit: audit.event(actor, action, before/after)
        AAPI-->>UI: 200
    else denied (e.g., auditor)
        AuthZ-->>AAPI: deny (deny-by-default)
        AAPI-)Audit: audit.event(denied attempt)
        AAPI-->>UI: 403
    end
    Note over AAPI,AuthZ: Same AuthorizationPort guards API and UI (FR-128).<br/>Virtual keys use inference-only scopes, never admin perms.
```

## Notes
- JWT validated against IdP **JWKS**; signing keys rotate/revoke (FR-093). AuthN failure → **fail
  closed** (401/403), [ADR-0009](../../adr/0009-fail-open-fail-closed-matrix.md) row 6.
- **Auditor** role is read-only + `audit:read`; a budget write is denied and the attempt audited
  (AC-US-072).
- Every sensitive decision (grant or deny) emits an **immutable, hash-chained** audit event (FR-101/113).

**Requirements:** FR-090..101, FR-113, FR-128/129; NFR-SEC05/09.
