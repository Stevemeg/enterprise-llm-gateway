# Local Validation Guide (Gate 2)

**Phase:** 5 — Backend · Living document
**Last updated:** 2026-07-15 (Milestone 3)

Two-gate validation. **Gate 1** runs in the assistant sandbox (ruff, mypy, pytest, import-linter).
**Gate 2** runs on a **real developer machine** with the approved toolchain (Python 3.13 via uv, real
PostgreSQL + Redis, Docker) to catch what the sandbox cannot. Run Gate 2 after every implementation
milestone and paste results back.

> TL;DR — one command:
> `./scripts/validate.sh` (macOS/Linux/WSL/Git-Bash) or `./scripts/validate.ps1` (Windows PowerShell).

## 1. Prerequisites
| Tool | Version | Why |
|------|---------|-----|
| **uv** | latest | Manages Python 3.13 + deps (`pyproject.toml`) |
| **Python** | 3.13 (provisioned by uv) | Runtime target |
| **Docker + Compose** | recent | Local PostgreSQL + Redis (`docker-compose.dev.yml`) |
| **git** | any | Repo |
| (optional) **curl** | any | Endpoint checks |

Install uv:
- macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `irm https://astral.sh/uv/install.ps1 | iex`

## 2. Environment setup
```bash
git clone <repo> && cd "Enterprise LLM Gateway & Cost Router"
cp backend/.env.example backend/.env        # non-secret local config
# (WSL/Git-Bash) make scripts executable:
chmod +x scripts/*.sh
```

## 3. Required services (PostgreSQL + Redis)
```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps      # wait for "healthy"
```
- PostgreSQL: `localhost:5432` (user/pw/db = `gateway`), image includes **pgvector**.
- Redis: `localhost:6379`.
- Stop: `docker compose -f docker-compose.dev.yml down` (add `-v` to wipe data).

## 4. Alembic migrations
Runtime/DDL split (ADR-0014): **migrations run as the owner/migrator; the app + tests run as the
least-privilege `app_rw` role** so RLS is actually enforced. Set both URLs:
```bash
cd backend
# runtime role the app + tests use (app_rw is NOSUPERUSER, NOBYPASSRLS):
export GATEWAY_DATABASE__URL="postgresql+asyncpg://app_rw:app_rw@localhost:5432/gateway"
# owner/migrator role used ONLY to run migrations (has DDL + CREATE ROLE):
export GATEWAY_MIGRATION_DATABASE__URL="postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"

# run migrations as the owner (the app_rw role cannot run DDL — by design):
GATEWAY_DATABASE__URL="$GATEWAY_MIGRATION_DATABASE__URL" uv run alembic upgrade head
GATEWAY_DATABASE__URL="$GATEWAY_MIGRATION_DATABASE__URL" uv run alembic current  # head = 0003_database_roles
```
The `app_rw` LOGIN role is created once at cluster init by `backend/docker/initdb`; migration
`0003` then grants it least privilege. If you recreate the DB, use `docker compose ... down -v`.
`./scripts/validate.{sh,ps1}` do the owner/runtime split and the bypass-containment check for you.

Windows PowerShell: set `$env:GATEWAY_DATABASE__URL` (app_rw) and
`$env:GATEWAY_MIGRATION_DATABASE__URL` (owner) accordingly.

### 4a. First-run bootstrap: give `app_rw` a login

Migration `0003` creates `app_rw` **without** a password (ADR-0011 - secrets never live in
migrations). LOGIN + password are environment-supplied: in dev via
`backend/docker/initdb/10-app-rw-role.sql`, which Postgres runs **only when the data volume is
first created**. If your volume predates that file you will see
`password authentication failed for user "app_rw"`. Fix it once:

```powershell
docker compose -f docker-compose.dev.yml exec postgres `
  psql -U gateway -d gateway -c "ALTER ROLE app_rw WITH LOGIN PASSWORD 'app_rw';"
```

Or re-provision from scratch (destroys dev data):
`docker compose -f docker-compose.dev.yml down -v` then `up -d`.

## 5. Quality gate (the individual commands)
Run from `backend/` (or use `./scripts/validate.sh`):
```bash
uv sync                                    # install into .venv (Python 3.13)
uv run ruff check .                        # lint + import order
uv run ruff format --check .               # formatting
uv run mypy src tests                      # strict typing
uv run lint-imports                        # architecture + crypto-boundary contracts
uv run pytest                              # all tests
uv run pytest --cov=src/gateway --cov-report=term-missing   # coverage
```

## 6. Running the application
```bash
./scripts/run-dev.sh          # or: uv run uvicorn gateway.config.bootstrap:create_app --factory --reload
```
> Note the entrypoint is `gateway.config.bootstrap:create_app` (module path under `src/`).

## 7. Endpoint verification
```bash
curl -s http://localhost:8000/livez      # {"status":"alive"}
curl -s http://localhost:8000/readyz     # 200 when DB reachable
curl -s http://localhost:8000/healthz    # {"status":"ok","checks":[{"name":"database","status":"ok"}...]}
curl -s http://localhost:8000/metrics    # Prometheus exposition (text/plain)
```
`X-Request-Id` is returned on every response (correlation id).

## 8. Expected successful output (abridged)
```
ruff .................. All checks passed!
ruff format ........... N files already formatted
mypy .................. Success: no issues found in N source files
lint-imports .......... Contracts: 7 kept, 0 broken.
pytest ................ N passed
healthz ............... {"status":"ok", ...}
```

## 9. Per-milestone validation matrix
| Milestone | Required services | Extra commands | Success criteria |
|-----------|-------------------|----------------|------------------|
| **M1 Foundation** | none | `validate.sh` | gate green; `/livez` `/healthz` `/metrics` respond |
| **M2 Database** | Postgres | `alembic upgrade head`; `pytest -m integration` | migrations apply; RLS/UoW integration green; `/readyz` 200 with Postgres |
| **M3 Auth (crypto+logic)** | none (unit) | `validate.sh` | JWT/API-key/refresh tests green; 7 import-linter contracts kept |
| **M3 Auth (persistence)** | Postgres | `pytest -m integration` | auth repositories pass against real Postgres + RLS |
| **M3d-2A.5 DB role hardening** | Postgres | `validate.sh` (owner migrate + app_rw tests) | app connects as `app_rw`; RLS blocks A↔B; `test_database_role.py` + bypass-containment gate green; **0 skipped** |
| **Later (routing/cache/…)** | Postgres, Redis | per milestone | as documented per slice |

## 10. Common failures & how to debug
| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `uv: command not found` | uv not installed/on PATH | Install uv (§1); restart shell |
| uv can't fetch Python 3.13 | offline / proxy | Allow `astral.sh` + GitHub; or `uv python install 3.13` on a network |
| `alembic upgrade` fails on `CREATE EXTENSION` | Postgres missing pgvector / `pg_stat_statements` not preloaded | Use `docker-compose.dev.yml` (image + preload configured) |
| `/readyz` returns 503 | DB unreachable | `docker compose ... ps`; check `GATEWAY_DATABASE__URL` |
| `connection refused :5432` | services not up | `docker compose -f docker-compose.dev.yml up -d` |
| mypy import errors | stale env | `uv sync` again; delete `.venv` and re-sync |
| import-linter "broken contract" | a layer/crypto-boundary violation | fix the offending import (see message); do not weaken the contract |
| tests hang | event loop / async fixture | ensure `asyncio_mode = auto` (configured); rerun `-p no:cacheprovider` |
| Windows: script blocked | execution policy | `Set-ExecutionPolicy -Scope Process RemoteSigned` then run `.ps1` |

## 11. Scripts reference
| Script | Purpose |
|--------|---------|
| `scripts/validate.sh` / `.ps1` | Full gate: sync + ruff + format + mypy + import-linter + pytest+coverage |
| `scripts/test-all.sh` / `.ps1` | Verbose tests + coverage (HTML); applies migrations if Postgres configured |
| `scripts/run-dev.sh` / `.ps1` | Migrate + run the API with `--reload` |

## 12. Success criteria (Gate 2 passes when)
- `validate.sh`/`.ps1` exits 0 (all of ruff, format, mypy, import-linter, pytest pass).
- With Postgres up: `alembic upgrade head` succeeds and `/readyz` returns 200.
- `/livez`, `/healthz`, `/metrics` respond as documented.
Paste the tail of `validate.sh` output back into the review to close the milestone.
