# ADR-0008: Authorization / RBAC model

- **Status:** Accepted
- **Date:** 2026-07-15
- **Deciders:** Principal Architect, Security Architect
- **Phase:** 2 — Architecture
- **Resolves blocking decision:** RBAC model
- **Resolves open question:** OQ-07 (final RBAC role set & permission granularity)

## Context & problem
Two distinct principals access the system: **human administrators** (via OIDC/JWT, FR-090..093) and
**applications** (via virtual API keys, FR-094..097). Authorization must be **deny-by-default,
least-privilege** (FR-100, FR-099), enforced identically in API and UI (FR-128), **tenant-scoped**
(FR-129), and auditable (FR-101). We must define the role set (FR-098) and a permission model granular
enough for enterprise separation-of-duties (e.g., an `auditor` who can read but never modify budgets —
AC-US-072) without becoming unmanageable.

## Decision drivers
- FR-090..101 (auth, keys, RBAC roles, least privilege, deny-by-default, audit).
- FR-128/129 (same RBAC in UI and API; tenant-scoped), FR-135..137 (teams/members).
- NFR-SEC04/SEC05 (ASVS L2, deny-by-default), Persona P-03 (separation of duties), RISK-S04.

## Options considered
### Option A — Flat roles with hard-coded checks at each endpoint
- **Pros:** Simple to start.
- **Cons:** Permission logic scattered/duplicated; hard to audit "who can do what"; brittle as features
  grow; violates least-privilege maintainability. Rejected.

### Option B — Full ABAC / policy engine (e.g., OPA/Rego or Cedar) from day one
- **Pros:** Extremely flexible; externalized policy.
- **Cons:** Operational + cognitive overhead; another component to run air-gapped; overkill for a role
  set that is fundamentally role-based; slower to reason about for enterprise buyers who expect named
  roles. Deferred as a future extension, not the core.

### Option C — **RBAC with a permission catalog, tenant scoping, and team membership** (roles = named sets of fine-grained permissions), with an authorization **port** that can later delegate to a policy engine
- **Roles** (FR-098): `owner`, `admin`, `operator`, `finance`, `auditor`, `developer` — each mapped to
  a **permission catalog** (e.g., `budget:read`, `budget:write`, `key:issue`, `provider:write`,
  `routing:write`, `audit:read`, `usage:read`, `policy:write`). Authorization = does the principal's
  role (within the resource's tenant/team scope) grant the required permission?
- **Two principal types:** admin JWT (roles) and virtual keys (**scopes** are a constrained subset:
  e.g., `infer:chat`, `infer:embed` — FR-095). Keys never carry admin permissions.
- **Pros:** Named roles enterprises expect + fine-grained permissions for separation of duties;
  centralized, testable authorization decision function; deny-by-default; tenant/team scoping composes
  with [ADR-0002](0002-multi-tenant-isolation-model.md); a clean `AuthorizationPort` leaves the door
  open to ABAC/OPA later without rework.
- **Cons:** Maintaining the role→permission matrix; still coarser than full ABAC (acceptable for v1).

## Decision
Adopt **Option C**: **RBAC over a fine-grained permission catalog**, tenant- and team-scoped, behind a
single **`AuthorizationPort`** with a central **policy decision function** used by *both* API and UI
(FR-128). Roles: **owner, admin, operator, finance, auditor, developer** (FR-098) — the definitive v1
set (resolves OQ-07); `auditor` is strictly read + `audit:read` (satisfies AC-US-072). Human access is
**OIDC → JWT** ([Authentication Architecture](../Architecture.md)); applications use **virtual keys**
whose **scopes** are a restricted inference-only subset (FR-094..097; hashed at rest, FR-097).
Authorization is **deny-by-default** (FR-100), least-privilege (FR-099), and every sensitive decision
is **audited** (FR-101) to the immutable audit log (FR-113). The permission catalog is data, enabling
custom roles later; a future ABAC/policy-engine adapter can back the same port if needed.

### Role → permission summary (v1)
| Permission | owner | admin | operator | finance | auditor | developer |
|-----------|:----:|:----:|:-------:|:------:|:------:|:--------:|
| tenant:manage | ✅ | – | – | – | – | – |
| team:manage / member:invite | ✅ | ✅ | – | – | – | – |
| key:issue / key:revoke | ✅ | ✅ | – | – | – | – (self, if allowed) |
| provider:write / model:write | ✅ | ✅ | ✅ | – | – | – |
| routing:write / policy:write | ✅ | ✅ | ✅ | – | – | – |
| budget:write | ✅ | ✅ | – | ✅ | – | – |
| budget:read / usage:read | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (own scope) |
| audit:read | ✅ | ✅ | – | – | ✅ | – |
| infer:chat / infer:embed (via keys) | — application principals only — | | | | | |

## Consequences
- **Positive:** Enterprise-recognizable roles with real separation of duties; one audited decision
  point; composes with tenancy; extensible to ABAC without rearchitecting.
- **Negative:** Role/permission matrix must be maintained and tested; coarser than ABAC (accepted).
- **Follow-ups:** Phase 3 models `role`, `permission`, `role_permission`, `membership`, `virtual_key`
  (+ scopes); Phase 9 implements the decision function, key hashing/rotation, and audit; Phase 13 tests
  least-privilege and cross-tenant denial (AC-US-071/072/100).

## Requirements satisfied
- Functional: FR-090..101, FR-128, FR-129, FR-135, FR-136, FR-137.
- Non-functional: NFR-SEC04, NFR-SEC05, NFR-SEC09.

## Review notes
Introduce the ABAC/policy-engine adapter (Option B) only if customers require attribute/condition-based
policies beyond roles; it slots behind `AuthorizationPort` as a new ADR.
