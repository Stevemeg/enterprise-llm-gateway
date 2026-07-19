#!/usr/bin/env bash
# Run the full test suite verbosely with coverage. If a real Postgres is configured
# (GATEWAY_DATABASE__URL points at postgresql+asyncpg://...), apply migrations first so
# integration tests exercise the real schema.
set -euo pipefail
cd "$(dirname "$0")/../backend"

uv sync

if [[ "${GATEWAY_DATABASE__URL:-}" == postgresql* ]]; then
  echo "==> Postgres detected; applying migrations (alembic upgrade head)"
  uv run alembic upgrade head
else
  echo "==> No Postgres configured; integration tests run against local SQLite"
fi

echo "==> pytest -v + coverage"
uv run pytest -v --cov=src/gateway --cov-report=term-missing --cov-report=html
echo ""
echo "Coverage HTML report: backend/htmlcov/index.html"
