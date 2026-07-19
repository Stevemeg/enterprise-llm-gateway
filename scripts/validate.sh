#!/usr/bin/env bash
# Gate 2 — full local validation on a real developer machine (Python 3.13 via uv).
# Mirrors the sandbox gate: format, lint, types, architecture, tests + coverage.
set -euo pipefail
cd "$(dirname "$0")/../backend"

echo "==> uv sync (Python 3.13 + deps)"
uv sync

echo "==> ruff check (lint + imports)"
uv run ruff check .

echo "==> ruff format --check"
uv run ruff format --check .

echo "==> mypy (strict)"
uv run mypy src tests

echo "==> import-linter (architecture contracts)"
uv run lint-imports

echo "==> PowerShell encoding guard (ASCII + BOM + CRLF)"
python3 ../scripts/check_powershell_encoding.py ../scripts

echo "==> migration guardrail (tenant tables must ENABLE+FORCE RLS + policy)"
python3 ../scripts/check_migration_guardrails.py migrations/sql

if [[ "${GATEWAY_DATABASE__URL:-}" == postgresql* ]]; then
  # Runtime/DDL split (ADR-0014): migrations run as the OWNER/migrator; the app + tests run
  # as the least-privilege app_rw role (GATEWAY_DATABASE__URL) so RLS is actually enforced.
  OWNER_URL="${GATEWAY_MIGRATION_DATABASE__URL:-${GATEWAY_DATABASE__URL}}"
  if [[ "${OWNER_URL}" == "${GATEWAY_DATABASE__URL}" ]]; then
    echo "   WARNING: GATEWAY_MIGRATION_DATABASE__URL not set; running migrations as the"
    echo "            runtime role. If it is app_rw this will fail (no DDL privilege) — set"
    echo "            GATEWAY_MIGRATION_DATABASE__URL to the owner/migrator URL (see .env.example)."
  fi

  echo "==> alembic upgrade head (as owner/migrator)"
  GATEWAY_DATABASE__URL="${OWNER_URL}" uv run alembic upgrade head
  GATEWAY_DATABASE__URL="${OWNER_URL}" uv run alembic current

  echo "==> Gate: runtime role must be NOSUPERUSER + NOBYPASSRLS (ADR-0014)"
  uv run python ../scripts/check_runtime_role.py
else
  echo "==> No Postgres configured; repo layer validated against SQLite in tests"
fi

echo "==> pytest + coverage"
uv run pytest --cov=src/gateway --cov-report=term-missing

echo ""
echo "✅ ALL LOCAL VALIDATION PASSED"
