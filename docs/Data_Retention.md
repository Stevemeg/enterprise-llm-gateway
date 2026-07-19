# Data Retention & Archival

**Phase:** 3 — Database Architecture · Draft for approval
**Last updated:** 2026-07-15

Per-entity retention and archival, supporting compliance (GDPR erasure NFR-C03, DPA-friendly logging
NFR-C06), residency (NFR-C02/C05), and cost/performance (bounded hot tables). Retention is
**configurable per tenant** where regulation requires; the values below are defensible defaults.

## 1. Retention classes

| Class | Meaning | Default window | Mechanism |
|-------|---------|----------------|-----------|
| **Permanent** | Reference/config/financial records | Life of entity / legal min (e.g., invoices 7y) | Soft-delete + audit |
| **Compliance** | Audit trail | 1–7 years (configurable) then archive | Partition detach → cold storage (immutable) |
| **Operational-long** | Aggregates/analytics | 13–25 months | Kept after raw archival |
| **Operational-hot** | Raw high-volume metering | 3–12 months hot → archive | Partition detach |
| **Transient** | Churn/ephemeral | 7–90 days | Prune (DELETE/TTL) |

## 2. Per-entity retention

| Entity | Class | Window (default) | Notes |
|--------|-------|------------------|-------|
| organization, app_user, service_account, project | Permanent | life; purge on erasure request | Soft-delete then hard-purge (NFR-C03) |
| oauth_identity, membership, project_member | Permanent | with parent | — |
| session | Transient | 30 days after expiry | Prune |
| refresh_token | Transient | until expiry + grace | Prune |
| role/permission/role_permission | Permanent | reference | — |
| api_key / api_key_scope | Permanent | until revoked + audit window | Keep revoked for audit trail |
| provider/model/routing_policy/rate_limit_policy/governance_policy/prompt_template/prompt_version | Permanent | life of config | prompt_version kept for reproducibility |
| price_table | Permanent | historical (cost reproducibility) | never delete past prices |
| provider_health | Transient | 7–30 days | Prune |
| embedding | Operational-hot | tied to cache TTL / model version | Delete with cache entry or on re-embed |
| semantic_cache_entry | Operational-hot | TTL per policy (e.g., hours–30 days) | Prune expired (FR-058) |
| budget | Permanent | current + history | For reporting |
| reservation | Transient | 7–30 days after settle | Prune settled/expired |
| **usage_ledger** | Operational-hot → Compliance | hot 3–12 months → archive; financial retention per policy | Partition detach + cold archive |
| usage_rollup | Operational-long | 13–25 months | Survives raw archival |
| billing_account | Permanent | life of customer | — |
| invoice | Permanent (financial) | 7 years | Legal |
| **audit_event** | Compliance | 1–7 years (configurable) then archive | Immutable; hash-chain verified on archive |
| feature_flag/configuration | Permanent | life of feature | — |
| notification | Transient | 90 days | Prune |
| background_job | Transient | succeeded 7 days; dead_letter 90 days | Prune |
| secret_reference | Permanent | life of secret | rotation audited (no values stored) |
| webhook | Permanent | life of subscription | — |
| webhook_delivery | Transient | 30–90 days | Prune |

## 3. Archival mechanics
- **Partitioned tables** (`usage_ledger`, `audit_event`): monthly partitions older than the hot window
  are **detached** (`DETACH PARTITION CONCURRENTLY`), exported compressed + encrypted to object storage
  / cold schema, then dropped from the hot cluster (see
  [`Partitioning_Strategy.md`](Partitioning_Strategy.md)). Archived data remains **restorable** for
  compliance queries ([`Backup_and_Recovery.md`](Backup_and_Recovery.md)).
- **Rollups** are computed **before** raw ledger archival so analytics survive.
- **Transient tables:** batched `DELETE` by a scheduled prune job (indexed on `expires_at`/`created_at`/
  `status`), sized to avoid bloat (autovacuum tuned; periodic `VACUUM`).

## 4. Right-to-erasure (GDPR) — NFR-C03
- **Erasure request** for a user/tenant triggers: soft-delete → purge of PII-bearing rows
  (`app_user`, `oauth_identity`, prompt/response content per `governance_policy` logging setting),
  and **redaction** of PII in retained records where full deletion conflicts with financial/audit
  retention (e.g., audit keeps the event, scrubs PII payload).
- **Cache & embeddings** for the subject are invalidated/deleted.
- The **audit trail of the erasure itself** is retained (immutable) as proof of compliance.
- Tenant deletion (FR-134) cascades tenant-owned rows (ON DELETE CASCADE) after the retention/hold
  window; append-only `audit_event`/archived `usage_ledger` follow compliance retention, not immediate
  cascade.

## 5. Residency & boundary
Retention/archival storage honors residency: archived partitions and backups stay in the tenant's
**home region** (SaaS) or **customer boundary** (self-host) — NFR-C02/C05, ADR-0010/0011.

## 6. Logging minimization — NFR-C06
`governance_policy.prompt_logging` / `response_logging` (`store`/`hash`/`drop`) control whether prompt/
response content is retained at all; default `hash`. This bounds sensitive-data retention at the source
(FR-118).

## 7. Configurability & governance
Windows above are **defaults**; per-tenant overrides (longer for compliance, shorter for
data-minimization) are stored in `configuration`/`governance_policy` and enforced by the prune/archive
jobs. Changes are audited.

## 8. Requirements traceability
NFR-C02/C03/C05/C06 (residency, erasure, boundary, minimization), FR-089 (telemetry retention),
FR-118 (logging policy), FR-113..115 (audit retention/immutability), FR-134 (tenant deletion),
ADR-0009/0010/0011.
