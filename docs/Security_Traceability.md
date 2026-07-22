# Security Traceability

**Phase:** 5 — Backend · Living document (started Milestone 3)
**Last updated:** 2026-07-15

Maps each **security control** to the ADR that mandates it, the STRIDE threat it mitigates, the
requirements it satisfies, the tests that verify it, and the module that implements it. Extremely
useful before penetration testing / security review (Phase 13). Modules marked *(M3)* are planned for
the authentication implementation step (this milestone, pending design approval).

## 1. Authentication controls

| Security Control | ADR | Threat (STRIDE) | FR | NFR | Tests | Module |
|------------------|-----|-----------------|----|-----|-------|--------|
| JWT signature validation (RS256) | ADR-0008 | Spoofing, Tampering | FR-090, FR-091 | NFR-SEC01, NFR-SEC04 | `test_jwt.py` *(M3)* | `adapters/security/jwt.py` *(M3)* |
| Algorithm agility / reject `alg:none` & alg-confusion | ADR-0008 | Spoofing | FR-091 | NFR-SEC04 | `test_jwt.py::alg_confusion` *(M3)* | `adapters/security/jwt.py` *(M3)* |
| `kid` selection + key rotation | ADR-0008 | Spoofing | FR-093 | NFR-SEC04 | `test_key_rotation.py` *(M3)* | `adapters/security/jwks.py` *(M3)* |
| JWKS publication (public keys) | ADR-0008 | Spoofing | FR-092, FR-093 | NFR-SEC04 | `test_jwks.py` *(M3)* | `adapters/security/jwks.py` *(M3)* |
| Clock-skew tolerance (leeway) | ADR-0008 | — (correctness) | FR-091 | NFR-SEC04 | `test_jwt.py::skew` *(M3)* | `adapters/security/jwt.py` *(M3)* |
| Access-token expiry enforcement | ADR-0008 | Elevation, Replay | FR-091 | NFR-SEC05 | `test_jwt.py::expiry` *(M3)* | `adapters/security/jwt.py` *(M3)* |
| API-key SHA-256 hashing (no plaintext) | ADR-0008, ADR-0011 | Info disclosure | FR-097 | NFR-SEC03 | `test_api_keys.py` *(M3)* | `adapters/security/api_keys.py` *(M3)* |
| Constant-time secret comparison | ADR-0008 | Info disclosure (timing) | FR-097 | NFR-SEC04 | `test_timing_safe.py` *(M3)* | `shared/secrets.py` *(M3)* |
| Secure random generation | ADR-0008 | Spoofing | FR-094, FR-097 | NFR-SEC04 | `test_secrets.py` *(M3)* | `shared/secrets.py` *(M3)* |
| Refresh-token rotation + reuse detection | ADR-0008 | Replay, Spoofing | FR-091 | NFR-SEC05, NFR-SEC09 | `test_refresh.py` *(M3)* | `application/auth/refresh_session.py` *(M3)* |
| Refresh-token hashed storage | ADR-0008, ADR-0011 | Info disclosure | FR-097 | NFR-SEC03 | `test_refresh.py` *(M3)* | `adapters/persistence/...` *(M3)* |
| OIDC id_token verification (iss/aud/nonce) | ADR-0008 | Spoofing, Replay | FR-092 | NFR-SEC01 | `test_oidc.py` *(M3)* | `application/auth/complete_oidc_login.py` *(M3)* |
| OIDC state + PKCE (login CSRF/replay) | ADR-0008 | Spoofing, Replay | FR-090 | NFR-SEC04 | `test_oidc.py::state_pkce` *(M3)* | `application/auth/oidc.py` *(M3)* |
| Service-account secret hashing + verify | ADR-0008 | Spoofing | FR-098 | NFR-SEC03 | `test_service_account.py` *(M3)* | `application/auth/authenticate_service_account.py` *(M3)* |
| Session revocation / logout | ADR-0008 | Elevation | FR-091 | NFR-SEC05 | `test_session.py` *(M3)* | `application/auth/logout.py` *(M3)* |
| Per-device session management | ADR-0008 | Elevation | FR-091 | NFR-SEC05 | `test_session.py` *(M3)* | `application/auth/sessions.py` *(M3)* |
| Auth failure fails closed (401) | ADR-0009 | Elevation | FR-090..097 | NFR-A04 | `test_auth_middleware.py` *(M3)* | `delivery/http/middleware/authentication.py` *(M3)* |
| Structured auth audit events | ADR-0008, ADR-0009 | Repudiation | FR-101, FR-113 | NFR-SEC09 | `test_auth_audit.py` *(M3)* | `adapters/audit/...` *(M3)* |
| Correlation id on auth events | ADR-0008 | Repudiation | FR-080 | NFR-O01 | `test_auth_audit.py` *(M3)* | `observability/logging.py` (M1) |
| Secret zeroization (retired keys) | ADR-0008 | Info disclosure | FR-093 | NFR-SEC03 | `test_key_rotation.py::zeroize` *(M3)* | `shared/secrets.py` *(M3)* |

## 2. Established controls (implemented, earlier milestones)

| Security Control | ADR | Threat | FR | NFR | Tests | Module |
|------------------|-----|--------|----|-----|-------|--------|
| Tenant isolation via RLS (`set_config`) | ADR-0002 | Info disclosure, Elevation | FR-130..132 | NFR-SEC07 | `test_rls.py`, `test_uow_sqlite.py`, `test_auth_rls_postgres.py` *(Postgres, Gate 2)* | `adapters/persistence/rls.py`, `uow.py` |
| **Database role isolation** (runtime = `app_rw`, NOSUPERUSER/NOBYPASSRLS; superuser bypasses RLS even under FORCE) | ADR-0014 | Info disclosure, Elevation | FR-130..132 | NFR-SEC07 | `test_database_role.py` *(bypass containment)*, validate.* Gate-2 role check | `migrations/versions/0003_database_roles.py`, `migrations/sql/0003_database_roles.sql`, `docker/initdb/10-app-rw-role.sql` |
| No secret values stored (references only) | ADR-0011 | Info disclosure | FR-022 | NFR-SEC03 | `test_database_settings.py` (safe_url) | `config/settings.py` |
| Log secret/PII redaction | ADR-0009 | Info disclosure | FR-010, FR-082 | NFR-SEC03 | `test_logging.py` | `observability/logging.py` |
| Fail-fast on missing config/secret | ADR-0009 | DoS/misconfig | FR-146 | NFR-A04 | `test_settings.py` | `config/settings.py` |
| Correlation id propagation | ADR-0008 | Repudiation | FR-080 | NFR-O01 | `test_app.py` | `delivery/http/middleware/request_context.py` |

## 3. Notes
- Rows marked *(M3)* are the authentication implementation deliverables of this milestone; each will
  land with its tests and this table updated to remove the marker.
- Full narrative + sequence diagrams: [Authentication_Architecture.md](Authentication_Architecture.md).
- Threat model context: [architecture/security/02-threat-model-stride.md](architecture/security/02-threat-model-stride.md).


## 4. Phase 4 architectural enforcement (ADR-0016)

Architecture-only; no new security controls. Listed here because these guards protect properties
that security depends on later — explainable decisions are what make an authorization denial
auditable.

| Control | ADR | Enforcement | Proven to fail |
|---|---|---|---|
| Routing decisions are explainable by construction | ADR-0016 inv. 3 | `RoutingDecision` returned by `AgentRuntime`; `reasoning_steps` never empty | ✅ Guard 1 (AST construction scan) |
| Only `AgentRuntime` may construct a `RoutingDecision` | ADR-0016 inv. 3 | `scripts/check_routing_decision_construction.py`, wired into `validate.ps1` | ✅ second construction site → FAIL |
| Agents may not orchestrate one another | ADR-0016 inv. 4 | import-linter | ✅ `planner` → `runtime` → BROKEN |
| Agent implementations are mutually independent | ADR-0016 inv. 4 | import-linter (independence) | ✅ `cost` → `policy` → BROKEN |
| Agents depend on protocols/domain only | ADR-0016 inv. 4 | import-linter | ✅ `health` → `adapters` → BROKEN |
| Tool consumers depend on the registry protocol only | ADR-0016 inv. 2 | import-linter | ✅ `catalog` → `in_memory_registry` → BROKEN |
| Registry implementations mutually independent | ADR-0016 inv. 2 | import-linter (independence) | ✅ `static_manifest` → `in_memory` → BROKEN |
| Registries constructed only in the composition root | ADR-0016 inv. 2 | `scripts/check_registry_construction.py` (AST), wired into `validate.ps1` | ✅ consumer construction → FAIL |
| Tool permissions fail closed (missing permission ⇒ denied) | ADR-0016 inv. 2 | `permitted()` requires every declared permission; enforced identically across both backends | ✅ parity + catalog tests |
| MCP consumers depend on the McpGateway protocol only | ADR-0016 inv. 2 | import-linter | ✅ `mcp_provisioner` → `in_memory_gateway` → BROKEN |
| MCP adapters never import ToolRegistry implementations | ADR-0016 inv. 2 | import-linter | ✅ `in_memory_gateway` → `in_memory_registry` → BROKEN |
| MCP gateways constructed only in the composition root | ADR-0016 inv. 2 | `scripts/check_mcp_construction.py` (AST), wired into `validate.ps1` | ✅ consumer construction → exit 1 |
| Tool permissions are operator-declared, never server-declared | ADR-0016 inv. 2 | `InMemoryMcpGateway` never reads permission metadata from MCP | ✅ `test_required_permissions_come_only_from_deployment_configuration` |
| MCP invocation fails closed (unknown tool / denied permission) | ADR-0009, ADR-0016 | `McpToolProvisioner` returns `McpResult(ok=False)`; denial does not name the missing permission | ✅ parity tests, both registry backends |
| RBAC denies an undeclared request | ADR-0016 inv. 5 | `AuthorizationStage` blocks when no requirement is declared | ✅ `test_undeclared_requirement_blocks` |
| RBAC permissions are tenant-scoped | ADR-0002, ADR-0016 | Resolver keyed by `(organization_id, principal_id)` | ✅ `test_known_principal_in_wrong_organization_blocks` |
| RBAC denial does not name the missing permission | ADR-0009 | Reason is generic; detail goes to audit annotations | ✅ `test_denial_reason_never_names_the_missing_permission` |
| Permission requirements are declared by the producer, not the enforcer | ADR-0016 inv. 5 | `application/authorization/requirements.py` owns the contract | ✅ `test_declared_requirement_is_what_the_stage_consumes` |
| Routing decisions remain the sole explanation | ADR-0016 inv. 3 | `RoutingExecution` limited to `{decision, provider}` | ✅ `test_routing_decision_is_the_only_explanation_object` |
| Routing engine cannot author a decision | ADR-0016 inv. 3 | `scripts/check_routing_decision_construction.py` | ✅ engine construction → exit 1 |
| Only one application component orchestrates the runtime | ADR-0016 inv. 3 | `scripts/check_routing_engine.py` (Guard L) | ✅ second caller → exit 1 |
| Provider catalogue is tenant-scoped | ADR-0002 | `InMemoryProviderCatalog` keyed by organization | ✅ `test_another_tenant_sees_an_empty_catalog` |
| Engine defects cannot masquerade as denials | ADR-0016 inv. 3 | `RoutingIntegrityError` raised, never recorded | ✅ `test_catalog_disagreement_raises_instead_of_faking_a_denial` |
| Provider execution never overrides an unrouted decision | ADR-0016 Slice 7 | `ProviderExecutor.execute()` refuses any `RoutingExecution` where `routed` is `False` before calling the client | ✅ `test_unrouted_execution_is_never_sent_to_the_client`, `test_policy_denial_is_never_sent_to_the_client` |
| Provider clients constructed only in the composition root | ADR-0016 Slice 7 | `scripts/check_provider_construction.py` (AST), wired into `validate.ps1`/`validate.sh` | ✅ consumer construction → exit 1 |
| Provider client implementations are mutually independent | ADR-0016 Slice 7 | import-linter (independence) | ✅ `fake_client` → `in_memory_client` → BROKEN |
| Only the routing engine may reach `AgentRuntime` (extends to provider execution) | ADR-0016 inv. 3, Slice 7 | `scripts/check_routing_engine.py` (Guard L, reused unmodified from Slice 6) | ✅ `AgentRuntime` reference in `provider_executor.py` → exit 1 |
| Provider failures are data, never exceptions | ADR-0009, ADR-0016 Slice 7 | `ProviderClient.invoke()` returns `ProviderResponse(ok=False, ...)`, mirroring `McpResult` | ✅ `test_provider_failure_is_data_not_an_exception` |

