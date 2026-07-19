# Contributing (Backend)

How to make changes to the backend. Binding for all contributors and AI-assisted changes. Complements the
[Backend Implementation Guide](../docs/Backend_Implementation_Guide.md) and [STYLE_GUIDE.md](STYLE_GUIDE.md).

## 1. Golden rules
1. **Respect the layers.** Dependencies point inward (see [ARCHITECTURE.md](ARCHITECTURE.md)); violations
   fail CI (import-linter).
2. **Test-first.** Write/adjust tests with the change; keep Quality Gates green.
3. **One phase at a time.** Follow the approved phase; don't implement future phases early.
4. **No secrets in code or logs.** Secrets are references (ADR-0011); keys/tokens are hashed.
5. **Change the contract? Change the docs.** Update OpenAPI/ADR/guide in the same PR.

## 2. Workflow
1. Pick up work tied to an approved phase / issue.
2. Branch: `feat/<area>-<short>`, `fix/<area>-<short>`, `chore/...`, `docs/...`.
3. Implement within your module's [ownership](../docs/Backend_Implementation_Guide.md#4-module-ownership);
   cross-cutting changes get the owning role's review (CODEOWNERS).
4. Add tests (unit + integration as applicable); run the full local gate (§4).
5. Open a PR using the checklist (§5); keep PRs small and single-purpose.
6. Squash-merge after approvals + green CI.

## 3. Commits & PRs
- **Conventional Commits** (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`). Reference the issue.
- PR description states: what, why, which FR/NFR/ADR, and test evidence.
- Breaking API/schema changes require an ADR and follow the
  [versioning](../docs/API_Versioning_Strategy.md)/[migration](../docs/Migration_Strategy.md) policies.

## 4. Local quality gate (must pass before pushing)
```
uv sync                        # resolve/install deps into .venv (Python 3.13)
uv run ruff check .            # lint + import order
uv run ruff format --check .   # formatting
uv run mypy src                # strict typing
uv run lint-imports            # layer/dependency contracts (import-linter)
uv run pytest                  # unit + integration (SQLite locally; Postgres in CI)
```
Coverage **>=90% meaningful** where practical; the RLS-isolation and budget-concurrency tests are
mandatory and must pass (RISK-T03/T05, NFR-SEC07).

## 5. PR checklist (Definition of Done)
- [ ] Layer/import rules respected (no inward framework imports; ports over concretes).
- [ ] Business logic in `application`/`domain`, not `delivery`/`adapters`/worker.
- [ ] Repositories used within an RLS-scoped UoW; no provider call inside a DB transaction.
- [ ] Typed exceptions raised; error mapping only at the HTTP edge ([API_Error_Model](../docs/API_Error_Model.md)).
- [ ] Tests added/updated; gates green; coverage maintained.
- [ ] No secret/PII in code, fixtures, or logs.
- [ ] Docs/OpenAPI/ADR updated if behavior or contract changed; changelog entry if API changed.
- [ ] Observability: new hot paths emit spans/metrics/structured logs with `request_id`.

## 6. Migrations
- Schema changes are **forward-only, ordered** migrations per
  [Migration_Strategy](../docs/Migration_Strategy.md); expand->migrate->contract for breaking changes.
- Never edit an applied migration; add a new one. CI applies migrations to an ephemeral DB and checks
  drift + RLS + referential integrity.
- **Tenant-table guardrail (enforced, ADR-0002/0014).** A migration that introduces a **tenant-scoped
  table** (any table with an `organization_id` column) may not merge unless it also:
  1. `ENABLE ROW LEVEL SECURITY` **and** `FORCE ROW LEVEL SECURITY` on the table;
  2. creates a tenant-isolation `CREATE POLICY` (`organization_id = current_setting('app.current_org', true)::uuid`);
  3. keeps `app_rw` reachable — automatic via `ALTER DEFAULT PRIVILEGES` (migration 0003); do **not**
     grant `BYPASSRLS` to any runtime role;
  4. updates [`Security_Traceability.md`](../docs/Security_Traceability.md) if it adds a security control.
  Items 1–3 are checked automatically by `scripts/check_migration_guardrails.py` (run in `validate.*`
  and CI); `test_default_privileges.py` proves the app_rw auto-grant. Genuinely global/NULL-org
  reference tables are exempted explicitly in the checker (with justification).

## 7. Adding an adapter (common task)
1. Confirm the **port** exists in `application/ports` (add it there if not — with domain/application only).
2. Implement `adapters/<area>/<backend>_adapter.py` against the port; no cross-adapter imports.
3. Bind it in `config/container.py` (composition root) — the only place it's referenced concretely.
4. Add contract tests (e.g., provider fixtures) + integration tests.

## 8. Security & review
- Security-sensitive areas (auth, RBAC, secrets, governance, RLS) require Security-owner review.
- Run the security scan locally when touching those areas; CI runs SAST/dependency/container scans
  (NFR-SEC06) and blocks High/Critical.

## 9. AI-assisted contributions
Same rules apply. Generated code must pass all gates, respect layers, and include tests. Do not accept
suggestions that import frameworks into `domain`/`application` or that embed secrets.

## 10. Module completion bar (raised, from Milestone 2)
No production module is complete until **all** of the following exist and pass:
- **Documentation** — module + public API docstrings; docs/ADR updated if behavior changed.
- **Unit tests** — behavior covered with fakes for ports (no I/O).
- **Failure-mode tests** — the module's degradation path (fail-open/closed per ADR-0009).
- **Type checking** — `mypy --strict` clean.
- **Lint/format** — `ruff check` + `ruff format --check` clean.
- **Architecture contracts** — `import-linter` clean (layer/framework rules).
- **Performance considerations** — documented (hot-path cost, pooling, transaction scope).
- **Traceability** — a row added/updated in `docs/Code_Traceability.md`.


## 11. Security-sensitive modules (negative-test gate)
Every **security-sensitive** module (auth, crypto, RBAC, secrets, RLS, governance) must have **at least
one negative / failure-mode test for every public function or method** — proving denial/rejection, not
only the success path. CI (Phase 11) fails a security module that adds a public API without a
corresponding failure-mode test. See docs/Security_Test_Plan.md §3.
