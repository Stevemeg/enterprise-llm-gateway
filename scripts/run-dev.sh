#!/usr/bin/env bash
# Start the API locally with auto-reload. Requires reachable Postgres + Redis
# (see docker-compose.dev.yml). Health: http://localhost:8000/healthz
set -euo pipefail
cd "$(dirname "$0")/../backend"

uv sync
echo "==> Applying migrations (best-effort; requires Postgres)"
uv run alembic upgrade head || echo "WARN: migrations skipped (is Postgres up?)"

echo "==> uvicorn on http://localhost:8000  (docs: /docs, health: /healthz, metrics: /metrics)"
exec uv run uvicorn gateway.config.bootstrap:create_app --factory --reload --host 0.0.0.0 --port 8000
