# Start the API locally with auto-reload (Windows/PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")

uv sync
Write-Host "==> Applying migrations (best-effort; requires Postgres)"
try { uv run alembic upgrade head } catch { Write-Host "WARN: migrations skipped (is Postgres up?)" }

Write-Host "==> uvicorn on http://localhost:8000  (docs: /docs, health: /healthz, metrics: /metrics)"
uv run uvicorn gateway.config.bootstrap:create_app --factory --reload --host 0.0.0.0 --port 8000
