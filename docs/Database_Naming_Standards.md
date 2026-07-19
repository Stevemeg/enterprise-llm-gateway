# Database Naming Standards

**Phase:** 3 — Database Architecture (governance artifact) · Draft for approval
**Last updated:** 2026-07-15

Canonical naming rules for the database layer. These **document and standardize** the conventions
already used in [`Schema.sql`](Schema.sql); they **do not change the schema**. All future migrations
(Phases 5–15) must conform. Rationale: predictability, greppability, tool-friendliness, and reviewability
(NFR-M03/M06).

## 1. General rules
- **Case:** `snake_case` everywhere. No camelCase, no quoted mixed-case identifiers.
- **Language:** English, lowercase, ASCII only.
- **Singular** nouns for table names (`app_user`, not `users`).
- **No reserved words** as bare identifiers — `user` → `app_user`.
- **Full words** over abbreviations, except well-known ones (`id`, `ref`, `ip`).
- **Deterministic prefixes** so objects sort/group by kind (see below).
- Identifiers ≤ 63 bytes (PostgreSQL limit); keep well under for composite index names.

## 2. Table naming
| Rule | Convention | Example |
|------|-----------|---------|
| Base table | singular noun | `organization`, `provider`, `invoice` |
| Child/detail table | `<parent>_<detail>` | `routing_policy_rule`, `prompt_version`, `webhook_delivery` |
| Associative (M2M) table | `<left>_<right>` (or domain-natural) | `role_permission`, `project_member`, `api_key_scope` |
| Reserved-word avoidance | prefix `app_` | `app_user` |
| Roll-up / derived | `<subject>_rollup` | `usage_rollup` |
| Ledger / event log | `<subject>_ledger`, `<subject>_event` | `usage_ledger`, `audit_event` |

Do **not** pluralize; do **not** prefix tables with `tbl_`.

## 3. Column naming
| Element | Convention | Example |
|---------|-----------|---------|
| Surrogate PK | `id` (uuid) | `id` |
| Foreign key | `<referenced_table_singular>_id` | `organization_id`, `provider_id`, `routing_policy_id` |
| Self / role-qualified FK | `<role>_<table>_id` or descriptive | `rotated_to` (self-ref), `created_by` (→ app_user) |
| Boolean | `is_` / `has_` prefix | `is_active`, `is_enabled`, `is_system`, `is_published` |
| Timestamp | `<event>_at` (timestamptz) | `created_at`, `updated_at`, `deleted_at`, `expires_at`, `observed_at` |
| Date (day grain) | `<subject>_date` | `bucket_date`, `period_start`/`period_end` (date) |
| Money | `<subject>_amount` / `<subject>_price...` (numeric) | `cost_amount`, `amount_limit`, `input_price_per_1k` |
| Count / measure | plural noun or `<subject>_count` | `prompt_tokens`, `hit_count`, `request_count` |
| Hash (never plaintext) | `<subject>_hash` (bytea) | `key_hash`, `token_hash`, `request_hash`, `entry_hash` |
| Enum-typed status | `status` / `state` | `status`, `state`, `result` |
| Free/semi-structured | domain noun (jsonb) | `settings`, `config`, `metadata`, `payload`, `detail` |
| Secret pointer | `*_secret_ref` / `secret_ref` (uuid → secret_reference) | `credential_secret_ref`, `secret_ref` |

Tenancy column is **always** `organization_id`. Never store secret values — only `*_hash` or
`*_secret_ref` (ADR-0011, NFR-SEC03).

## 4. Primary key conventions
- Every table has a **surrogate `id uuid`** PK, `DEFAULT gen_random_uuid()` (UUIDv7 app-side on hot
  append tables — Database_Design §2).
- **Partitioned tables** include the partition key in the PK: `PRIMARY KEY (id, created_at)`
  (`usage_ledger`, `audit_event`).
- **Associative tables** use a **composite natural PK** of the two FKs:
  `PRIMARY KEY (role_id, permission_id)`, `(project_id, user_id)`, `(api_key_id, scope)`.
- Constraint name: PostgreSQL default `<table>_pkey` is accepted (no manual rename needed).

## 5. Foreign key conventions
- Column: `<referenced_table>_id` (see §3). Multiple FKs to the same table are role-qualified
  (`created_by`, `updated_by`, `rotated_to`).
- **Explicit constraint name** when created via `ALTER`/when clarity helps:
  `<child>_<parent>_fk` — e.g., `provider_secret_ref_fk`.
- **Delete semantics** are explicit and intentional:
  - `ON DELETE CASCADE` for tenant-owned children of `organization` (tenant deletion, FR-134).
  - `ON DELETE RESTRICT` where deletion must be blocked (`membership.role_id`).
  - `ON DELETE SET NULL` for optional references (`api_key.created_by`, `provider.credential_secret_ref`).
- Every FK column is **indexed** (see §7) unless it is the leading column of the PK.

## 6. Unique & check constraint naming
| Kind | Convention | Example |
|------|-----------|---------|
| Unique | `<table>_<cols>_key` | `organization_slug_key`, `app_user_org_email_key`, `price_model_effective_key` |
| Check | `<table>_<purpose>_ck` | `budget_amount_ck`, `reservation_cost_ck`, `membership_principal_ck`, `slug` via `organization_slug_format` |
| Exclusion (future) | `<table>_<purpose>_excl` | (none yet) |

Check constraints encode invariants (non-negative money/tokens, valid period ranges, exactly-one
polymorphic principal, https URLs, path-length guard on secret references).

## 7. Index naming
- Prefix **`ix_`** for non-unique secondary indexes: `ix_<table>_<cols|purpose>`.
  Examples: `ix_app_user_org`, `ix_price_table_model_current`, `ix_usage_ledger_org_time`.
- **Unique** indexes are expressed as `UNIQUE` constraints (`*_key`), not `ix_`.
- **Vector (HNSW)** index: `ix_<table>_hnsw` — `ix_embedding_hnsw`.
- **Partial** indexes keep the same name; the predicate is documented in
  [`Indexing_Strategy.md`](Indexing_Strategy.md) (e.g., `ix_api_key_org_project WHERE status='active'`).
- Composite index names list purpose or leading columns, not every column, to stay ≤63 bytes.

## 8. Constraint vs. trigger responsibilities
- Prefer **declarative constraints** (PK/FK/unique/check) over triggers.
- Triggers (added in implementation phases, not in the base schema) follow: **`trg_<table>_<action>_<timing>`**
  — e.g., `trg_organization_set_updated_at_biu` (before-insert-update), `trg_budget_scope_validate_bi`
  (validate polymorphic `scope_id`), `trg_audit_event_hash_bi` (compute hash chain). Timing suffixes:
  `bi`(before insert), `bu`(before update), `biu`(before insert/update), `ai`(after insert).
- Trigger **functions**: `fn_<purpose>()` — e.g., `fn_set_updated_at()`, `fn_audit_hash_chain()`.

## 9. Partition naming
- Range partitions of a monthly-partitioned table: **`<parent>_<YYYY>_<MM>`**.
  Examples: `usage_ledger_2026_07`, `audit_event_2026_08`.
- Future hash sub-partitions (escalation path): **`<parent>_<YYYY>_<MM>_p<N>`**.
- A default/catch-all partition is intentionally **avoided** (inserts must match a real month; the
  partition-automation job pre-creates future months — [`Partitioning_Strategy.md`](Partitioning_Strategy.md)).

## 10. Sequence naming
- The design uses **UUID surrogate keys**, so there are **no serial/identity sequences for PKs**.
- Where a human-facing monotonic number is required (e.g., an invoice number), use a **named sequence**
  `seq_<subject>` (e.g., `seq_invoice_number`) or a per-tenant counter table — decided in the owning
  phase; never as a table PK. Ordered `version` columns (e.g., `prompt_version.version`) are
  application-assigned integers, not database sequences.

## 11. Migration naming
- Files: **`<NNNN>__<verb>_<subject>.sql`** with a zero-padded, monotonically increasing ordinal, e.g.
  `0001__create_core_tenancy.sql`, `0007__add_secret_reference_fk.sql`, `0015__enable_rls_policies.sql`.
  (`__` separates ordinal from description.)
- One logical change per migration; **forward-only**, with a compensating down for emergencies
  ([`Migration_Strategy.md`](Migration_Strategy.md)).
- The applied-migrations ledger table is `schema_migrations`.
- Seed migrations: `<NNNN>__seed_<subject>.sql` (idempotent upserts).

## 12. Enum type naming
- Enum types are singular `snake_case` describing the domain: `org_status`, `budget_scope`,
  `reservation_status`, `cache_hit_type`, `logging_policy`. Values are lowercase `snake_case`.

## 13. Database role naming
- Runtime roles: `app_rw`, `app_worker`, `app_reconciler`; DDL role `migrator`; cross-tenant
  maintenance `rls_bypass` ([`RLS_Strategy.md`](RLS_Strategy.md)). Prefix application roles with `app_`.

## 14. RLS policy naming
- One policy per tenant table: **`<table>_tenant_isolation`** — e.g., `budget_tenant_isolation`,
  `usage_ledger_tenant_isolation` (as in `Schema.sql`).

## 15. Conformance
Any object that cannot follow a rule documents the exception inline and in
[`Database_Design.md`](Database_Design.md). CI (Phase 11) includes a lightweight naming linter that
checks table/column/index prefixes against these rules and fails on violation (NFR-M05/M06).
