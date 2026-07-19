# API Implementation Map

**Phase:** 4 — API Contracts · Draft for approval
**Last updated:** 2026-07-15

Links every endpoint group to its ADRs, FRs, NFRs, database tables, future backend & frontend modules,
tests, and observability. This is the **implementation roadmap for the API layer** (Phases 5–13) and the
closing traceability from contract → requirement → decision → data → code → test. Endpoints:
[`api/OpenAPI.yaml`](api/OpenAPI.yaml) (53 paths, 87 operations). DB: [`Schema.sql`](Schema.sql). Modules:
[`Architecture_Implementation_Map.md`](Architecture_Implementation_Map.md).

## Legend
DB = tables read (R) / written (W). Backend/Frontend = future module (Phases 5–9 / 6). Tests = key
scenarios ([`API_Testing_Strategy.md`](API_Testing_Strategy.md)). Obs = key signals (FR-080..088).

---

## Inference  (tag: Inference)
| Endpoints | ADRs | FR | NFR | DB | Backend | Frontend | Tests | Obs |
|-----------|------|----|-----|----|---------|----------|-------|-----|
| `POST /chat/completions`, `/completions`, `/embeddings` | 0001,0003,0004,0006,0009,0012 | 001-010,050-058,060-063,070-073,110-117 | P01,P02,P04,P05,P06 | R: api_key, governance_policy, budget, provider, model, price_table, semantic_cache_entry, embedding, routing_policy; W: reservation, usage_ledger(via events), embedding(async) | delivery/http/inference, application/usecases/inference, routing, cache, budget, providers | Dev "getting started" panel | OpenAI-compat, streaming, budget-402, failover, cache isolation, residency | request span, X-Cache, cost, failover count |
| `GET /models`, `/models/{id}` | 0003 | 004,005 | M02 | R: model, provider | registry | Model catalog | list/get, tenant visibility | model list metric |

## Authentication  (tag: Authentication)
| `POST /auth/token`, `/auth/refresh`, `/auth/logout` | 0008 | 090-093 | SEC01,SEC05 | R/W: session, refresh_token, oauth_identity, app_user | adapters/oidc, auth | Login/SSO | token exchange, rotation, reuse-detection | auth success/failure |

## Organizations & Users & Projects  (tags: Organizations, Users, Projects)
| `/organizations*` | 0002,0010,0011 | 130-134 | SEC07,S03,D01 | R/W: organization | tenancy | Org settings | create/isolation, delete-gated | config-change audit |
| `/users*` | 0008 | 090,131,135,137 | SEC05 | R/W: app_user, membership | identity | Members admin | invite, update, remove | security audit |
| `/projects*` | 0004,0002 | 135,136 | S06 | R/W: project, project_member | tenancy | Projects admin | CRUD, member add/remove, scoping | config-change audit |

## API Keys & Service Accounts  (tags: API Keys, Service Accounts)
| `/api-keys*`, `/api-keys/{id}/rotate` | 0008 | 094-097 | SEC03 | R/W: api_key, api_key_scope | auth/keys | Keys UI | issue-once, scope enforce, rotate/revoke | key lifecycle audit |
| `/service-accounts*` | 0008 | 098 | SEC05 | R/W: service_account, membership | identity | Service accounts | CRUD, RBAC | security audit |

## Providers & Models  (tags: Providers, Models)
| `/providers*`, `/providers/{id}/health` | 0003,0011 | 020-029,037,038 | M02,A02 | R/W: provider, provider_health; R: secret_reference | adapters/providers, routing/health | Providers UI | register, enable/disable, health | provider share/health |
| `/admin/models*`, `/price-tables` | 0003 | 021,028,074,075 | — | R/W: model, price_table | registry | Models & pricing | CRUD, price versioning | model enable audit |

## Routing & Prompts  (tags: Routing Policies, Prompt Templates)
| `/routing-policies*` | 0012 | 030-041,116,117 | P01,A02,M02 | R/W: routing_policy, routing_policy_rule; R: model | routing | Routing editor | policy CRUD, residency validate | routing decisions |
| `/prompt-templates*`, `/versions` | 0006 | 058 | — | R/W: prompt_template, prompt_version | prompt | Prompt UI | version immutability, cache-key invalidation | template change audit |

## Cache & Embeddings  (tags: Semantic Cache, Embeddings Admin)
| `GET /cache/entries`, `DELETE /cache/entries` | 0006 | 050-058 | P02,P03,SEC07 | R/W: semantic_cache_entry; R: embedding | cache | Cache analytics | purge (audited), isolation | hit rate, purge audit |
| `/admin/embedding-config` | 0007 | 054-058 | P03,D05 | R/W: configuration (embedding) | cache/embeddings | Embedding settings | config change, re-embed trigger | embed config audit |

## Budgets, Usage, Billing  (tags: Budgets, Usage, Billing)
| `/budgets*` | 0004 | 060-069 | P05 | R/W: budget; R: reservation, usage_ledger | budget | Budgets UI | create, hard-stop, most-restrictive | budget threshold events |
| `GET /usage`, `/usage/export` | 0004,0005 | 070-077,086 | O05,S05 | R: usage_rollup, usage_ledger | analytics | Usage dashboards | aggregate, export, keyset | usage freshness |
| `/billing*` | — | — | — | R: billing_account, invoice | billing | Billing UI | account/invoice read | — |

## Governance & RBAC  (tags: Audit, RBAC)
| `GET /audit-events` | 0009 | 113-115 | SEC09 | R: audit_event | governance/audit | Audit viewer | read-only, immutability, time-window | audit read |
| `/roles`, `/permissions`, `/memberships*` | 0008 | 098-101 | SEC05,SEC09 | R/W: role, permission, role_permission, membership | authz | RBAC UI | least-privilege, deny-by-default | authz decisions |

## Rate Limits, Flags, Notifications, Webhooks  (tags: Rate Limits, Feature Flags, Notifications, Webhooks)
| `/rate-limits*` | — | 064,065 | S06 | R/W: rate_limit_policy | budget/limits | Rate-limit UI | 429 behavior, scope | rate-limit deny |
| `/feature-flags*` | — | — | — | R/W: feature_flag | platform/config | Flags UI | upsert, scoping | flag change audit |
| `/notifications*` | 0005 | 066,085 | — | R: notification | notifications | Notifications | list/status | delivery status |
| `/webhooks*`, `/deliveries` | 0005,0011 | 061,066,037,038,096 | SEC | R/W: webhook, webhook_delivery; R: secret_reference | webhooks | Webhooks UI | signing, retries/DLQ, idempotency | delivery/DLQ metrics |

## Health & Metrics  (tags: Health, Metrics)
| `/healthz`, `/readyz`, `/livez`, `/metrics` | 0005 | 080,081 | O03 | — (probes dependencies) | delivery/ops | Status widget | probe checks, scrape | golden signals |

---

## Coverage & closure
- **Every one of the 87 operations** belongs to a group above; each group maps to ≥1 ADR, its FRs/NFRs,
  the DB tables it touches, a future backend module, a frontend module (where user-facing), tests, and
  observability signals.
- **DB completeness:** all 40 tables are reachable from at least one endpoint group (identity/RBAC/config
  via admin; cache/ledger/reservation via inference + workers; audit via governance). Worker-owned tables
  (`usage_rollup`, `background_job`, `webhook_delivery`, append to `usage_ledger`/`audit_event`) are
  written off the API path per [`Database_Dependency_Map.md`](Database_Dependency_Map.md).
- **ADR traceability:** ADR-0001/0003/0004/0006/0007/0008/0009/0011/0012 each drive ≥1 endpoint group;
  ADR-0002 (tenancy/RLS) and ADR-0010 (multi-region) are cross-cutting (every tenant endpoint + servers).
- **Requirement closure:** the inference + admin surfaces together realize PR-01..PR-12
  ([`PRD.md`](PRD.md)); this map + [`Traceability_Matrix.md`](Traceability_Matrix.md) close user need →
  requirement → decision → schema → endpoint → test.

## Next phase
Phase 5 (Backend) implements these contracts against the Phase-3 schema using the Phase-2 module
boundaries — starting with the inference hot path (inference API + providers + routing + budget + cache)
and the auth/RBAC core.
