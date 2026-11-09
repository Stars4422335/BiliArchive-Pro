<#
.SYNOPSIS
    Run every check this project has and print one verdict.

.DESCRIPTION
    Runs the backend suite with the coverage floor, the linters, the frontend
    suite, and the same suites inside Docker, then prints a single table with
    one row per step and the overall result.

    The container steps use `run --rm`, so the containers are removed as soon
    as they finish and leave nothing behind.

.EXAMPLE
    pwsh -File scripts/test-all.ps1
    pwsh -File scripts/test-all.ps1 -SkipDocker
#>
[CmdletBinding()]
param(
    [switch]$SkipDocker
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

$python = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Action
    )
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    & $Action
    $code = $LASTEXITCODE
    $watch.Stop()
    $script:results.Add([pscustomobject]@{
        Step    = $Name
        Exit    = $code
        Seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1)
        Result  = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
    })
    if ($code -ne 0) {
        Write-Host "--- $Name FAILED (exit $code) ---" -ForegroundColor Red
    }
}

Invoke-Step 'pytest (local)' {
    & $python -m pytest tests -q -p no:cacheprovider --cov=app --cov=main --cov-report=term --cov-fail-under=74
}

Invoke-Step 'ruff' {
    & $python -m ruff check .
}

Invoke-Step 'mypy' {
    & $python -m mypy
}

Invoke-Step 'vitest (local)' {
    Push-Location (Join-Path $root 'webui')
    & npm test
    $code = $LASTEXITCODE
    Pop-Location
    $global:LASTEXITCODE = $code
}

Invoke-Step 'eslint (local)' {
    Push-Location (Join-Path $root 'webui')
    & npm run lint
    $code = $LASTEXITCODE
    Pop-Location
    $global:LASTEXITCODE = $code
}

if (-not $SkipDocker) {
    # The Docker daemon is reachable only while the host can route to the
    # engine VM. A VPN tunnel that installs a 192.168.0.0/16 route takes
    # 192.168.65.x with it, and the daemon stops answering. Say so instead
    # of reporting a green run that skipped the container checks.
    & docker version --format '{{.Server.Version}}' 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "!!! Docker daemon 不可达：容器内验证无法执行（标记为 SKIP，不算通过）" -ForegroundColor Yellow
        Write-Host "!!! 宿主到引擎 VM 的路由被隧道网卡（192.168.0.0/16）劫持；重启 Docker Desktop 或临时断开该隧道后重试。" -ForegroundColor Yellow
        $script:results.Add([pscustomobject]@{
            Step    = 'docker (容器内验证)'
            Exit    = 'skip'
            Seconds = 0
            Result  = 'SKIP'
        })
    } else {
        Invoke-Step 'pytest (docker)' {
            & docker compose --profile test run --rm --no-deps backend-test
        }

        Invoke-Step 'vitest (docker)' {
            & docker compose --profile test run --rm --no-deps webui-test
        }

        Invoke-Step 'docker build (runtime image)' {
            & docker build --tag biliarchive-pro:local .
        }
    }
}

Write-Host ""
Write-Host "================ TEST SUMMARY ================" -ForegroundColor Yellow
$results | Format-Table -AutoSize | Out-String -Width 120 | Write-Host

$failed = @($results | Where-Object { $_.Exit -ne 0 -and $_.Exit -ne 'skip' })
$skipped = @($results | Where-Object { $_.Exit -eq 'skip' })
if ($failed.Count -gt 0) {
    Write-Host "OVERALL: FAIL ($($failed.Count) of $($results.Count) steps failed)" -ForegroundColor Red
    Pop-Location
    exit 1
}
if ($skipped.Count -gt 0) {
    Write-Host "OVERALL: INCOMPLETE ($($skipped.Count) step(s) skipped; 未完成的验证不算通过)" -ForegroundColor Yellow
    Pop-Location
    exit 2
}

Write-Host "OVERALL: PASS ($($results.Count) of $($results.Count) steps green)" -ForegroundColor Green
Pop-Location
exit 0
