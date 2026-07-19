# Run the full test suite with coverage (Windows/PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")

uv sync

if ($env:GATEWAY_DATABASE__URL -like "postgresql*") {
    Write-Host "==> Postgres detected; applying migrations (alembic upgrade head)"
    uv run alembic upgrade head
} else {
    Write-Host "==> No Postgres configured; integration tests run against local SQLite"
}

Write-Host "==> pytest -v + coverage"
uv run pytest -v --cov=src/gateway --cov-report=term-missing --cov-report=html
Write-Host ""
Write-Host "Coverage HTML report: backend/htmlcov/index.html"
