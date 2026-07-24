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

Write-Host "==> validation parity guard (validate.sh and validate.ps1 must match)"
uv run python ..\scripts\check_validation_parity.py ..\scripts
if ($LASTEXITCODE -ne 0) { throw "Validation scripts have drifted." }

Write-Host "==> RoutingDecision construction guard (only AgentRuntime may build one)"
uv run python ..\scripts\check_routing_decision_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "RoutingDecision construction guard failed (ADR-0016 invariant 3)." }

Write-Host "==> Registry construction guard (only the composition root may build one)"
uv run python ..\scripts\check_registry_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Registry construction guard failed (ADR-0016 invariant 2)." }

Write-Host "==> MCP construction guard (only the composition root may build one)"
uv run python ..\scripts\check_mcp_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "MCP construction guard failed (ADR-0016 invariant 2)." }

Write-Host "==> Resolver construction guard (only the composition root may build one)"
uv run python ..\scripts\check_resolver_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Resolver construction guard failed (ADR-0016 invariant 2)." }

Write-Host "==> Routing engine guard (construction + sole AgentRuntime caller)"
uv run python ..\scripts\check_routing_engine.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Routing engine guard failed (ADR-0016 invariants 2-3)." }

Write-Host "==> Provider construction guard (only the composition root may build one)"
uv run python ..\scripts\check_provider_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Provider construction guard failed (ADR-0016 Slice 7)." }

Write-Host "==> Accounting construction guard (only the composition root may build one)"
uv run python ..\scripts\check_accounting_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Accounting construction guard failed (ADR-0016 Slice 8)." }

Write-Host "==> Execution construction guard (cache/dedup/coordinator only in the composition root)"
uv run python ..\scripts\check_execution_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Execution construction guard failed (ADR-0016 Slice 10)." }

Write-Host "==> Pipeline construction guard (the request path is composed only in the composition root)"
uv run python ..\scripts\check_pipeline_construction.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Pipeline construction guard failed (ADR-0016 invariant 5)." }

Write-Host "==> Metric cardinality guard (bounded, non-sensitive metric labels)"
uv run python ..\scripts\check_metric_cardinality.py src\gateway
if ($LASTEXITCODE -ne 0) { throw "Metric cardinality guard failed (NFR-SEC03)." }

Write-Host "==> migration guardrail (tenant tables must ENABLE+FORCE RLS + policy)"
uv run python ..\scripts\check_migration_guardrails.py migrations\sql
if ($LASTEXITCODE -ne 0) { throw "Tenant-table RLS guardrail failed (ADR-0002/0014)." }

$postgresConfigured = ($env:GATEWAY_DATABASE__URL -like "postgresql*")
if ($postgresConfigured) {
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
$pytestOutput = & uv run pytest --cov=src/gateway --cov-report=term-missing 2>&1
$pytestOutput | ForEach-Object { Write-Host $_ }
$pytestExit = $LASTEXITCODE
if ($pytestExit -ne 0) { throw "pytest FAILED - validation did NOT pass." }

# Three terminal states, because PASS/FAIL alone cannot express "the gate never ran".
# A run that skips every integration test is not a pass - it is an unexecuted gate, and
# reporting that as green is how an unverified change ships believing it was validated.
$joined = ($pytestOutput | Out-String)
$skipped = 0
if ($joined -match "(\d+)\s+skipped") { $skipped = [int]$Matches[1] }

Write-Host ""
if (-not $postgresConfigured) {
    Write-Host "INCOMPLETE - Gate 2 did NOT run" -ForegroundColor Yellow
    Write-Host "  Postgres was not configured, so migrations, the runtime-role check and the"
    Write-Host "  integration tests never executed ($skipped skipped)."
    Write-Host "  Gate 1 passed. Runtime validation is NOT verified."
    Write-Host "  Set GATEWAY_DATABASE__URL and GATEWAY_MIGRATION_DATABASE__URL, then re-run."
    exit 2
}
if ($skipped -ne 0) {
    Write-Host "FAIL - Postgres is configured but $skipped test(s) were skipped" -ForegroundColor Red
    Write-Host "  With Gate 2 available every test must execute. Investigate the skips."
    exit 1
}
Write-Host "PASS - ALL LOCAL VALIDATION PASSED (Gate 1 + Gate 2, 0 skipped)" -ForegroundColor Green
