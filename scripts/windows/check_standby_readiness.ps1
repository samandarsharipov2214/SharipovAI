param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$MaximumBackupAgeSeconds = $(if ($env:SHARIPOVAI_STANDBY_MAX_BACKUP_AGE_SECONDS) { [int]$env:SHARIPOVAI_STANDBY_MAX_BACKUP_AGE_SECONDS } else { 7200 })
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $ProjectRoot "tools\standby_health_report.py"
if (-not (Test-Path $python)) { throw "Python environment not found: $python" }
if (-not (Test-Path $reporter)) { throw "Standby health reporter not found: $reporter" }

& $python $reporter --project-root $ProjectRoot --maximum-age-seconds $MaximumBackupAgeSeconds
$exitCode = $LASTEXITCODE
$reportPath = Join-Path $ProjectRoot "runtime\standby_health.json"
if (Test-Path $reportPath) {
    $report = Get-Content $reportPath -Raw | ConvertFrom-Json
    $color = if ($report.status -eq "READY") { "Green" } elseif ($report.status -eq "STALE") { "Yellow" } else { "Red" }
    Write-Host "SharipovAI standby status: $($report.status)" -ForegroundColor $color
    Write-Host "Backup age: $($report.backup.age_seconds) seconds"
    Write-Host "Failover allowed: $($report.failover_allowed)"
    if ($report.reasons.Count -gt 0) { Write-Host ("Reasons: " + ($report.reasons -join "; ")) }
    Write-Host "Report: $reportPath"
}
exit $exitCode
