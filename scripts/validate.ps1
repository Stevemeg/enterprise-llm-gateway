# Gate 2 - full local validation (Windows/PowerShell). Requires uv on PATH.
# ASCII-only by design: Windows PowerShell 5.1 reads BOM-less files as Windows-1252, where a
# UTF-8 em dash decodes to a curly quote and silently breaks parsing.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")

Write-Host "==> uv sync (Python 3.13 + deps)"
uv sync
if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }

Write-Host "==> ruff check (lint + imports)"
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff check failed." }

Write-Host "==> ruff format --check"
uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { throw "ruff format check failed." }

Write-Host "==> mypy (strict)"
uv run mypy src tests
if ($LASTEXITCODE -ne 0) { throw "mypy failed." }

Write-Host "==> import-linter (architecture contracts)"
uv run lint-imports
if ($LASTEXITCODE -ne 0) { throw "import-linter contracts broken." }

Write-Host "==> PowerShell encoding guard (ASCII + BOM + CRLF)"
uv run python ..\scripts\check_powershell_encoding.py ..\scripts
if ($LASTEXITCODE -ne 0) { throw "PowerShell encoding guard failed." }

Write-Host "==> migration guardrail (tenant tables must ENABLE+FORCE RLS + policy)"
uv run python ..\scripts\check_migration_guardrails.py migrations\sql
if ($LASTEXITCODE -ne 0) { throw "Tenant-table RLS guardrail failed (ADR-0002/0014)." }

if ($env:GATEWAY_DATABASE__URL -like "postgresql*") {
    # Runtime/DDL split (ADR-0014): migrations run as the OWNER/migrator; the app and tests
    # run as the least-privilege app_rw role so RLS is actually enforced.
    if ($env:GATEWAY_MIGRATION_DATABASE__URL) {
        $ownerUrl = $env:GATEWAY_MIGRATION_DATABASE__URL
    } else {
        $ownerUrl = $env:GATEWAY_DATABASE__URL
        Write-Host "   WARNING: GATEWAY_MIGRATION_DATABASE__URL not set; running migrations as"
        Write-Host "            the runtime role. If that is app_rw this fails (no DDL privilege)."
        Write-Host "            Set it to the owner URL - see backend/.env.example."
    }

    Write-Host "==> alembic upgrade head (as owner/migrator)"
    $runtimeUrl = $env:GATEWAY_DATABASE__URL
    $env:GATEWAY_DATABASE__URL = $ownerUrl
    uv run alembic upgrade head
    $migrateExit = $LASTEXITCODE
    uv run alembic current
    $env:GATEWAY_DATABASE__URL = $runtimeUrl
    if ($migrateExit -ne 0) { throw "alembic upgrade failed." }

    Write-Host "==> Gate: runtime role must be NOSUPERUSER + NOBYPASSRLS (ADR-0014)"
    uv run python ..\scripts\check_runtime_role.py
    if ($LASTEXITCODE -ne 0) { throw "Bypass-containment gate failed (ADR-0014)." }
} else {
    Write-Host "==> No Postgres configured; repo layer validated against SQLite in tests"
}

Write-Host "==> pytest + coverage"
uv run pytest --cov=src/gateway --cov-report=term-missing
if ($LASTEXITCODE -ne 0) { throw "pytest FAILED - validation did NOT pass." }

Write-Host ""
Write-Host "ALL LOCAL VALIDATION PASSED" -ForegroundColor Green
