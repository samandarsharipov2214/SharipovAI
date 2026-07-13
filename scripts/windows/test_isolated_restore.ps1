param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SnapshotPath = "",
    [string]$DestinationRoot = "",
    [int]$RetainRuns = 12
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

if ($RetainRuns -lt 2 -or $RetainRuns -gt 52) {
    throw "RetainRuns must be between 2 and 52."
}
if (-not $SnapshotPath) {
    $SnapshotPath = Join-Path $ProjectRoot "runtime\remote_backups\current"
}
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path $ProjectRoot "runtime\restore_drills"
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$statusPath = Join-Path $ProjectRoot "runtime\restore_drill_status.json"
if (-not (Test-Path $python -PathType Leaf)) {
    throw "Python environment not found. Run setup_pc.ps1 first."
}
if (-not (Test-Path $SnapshotPath -PathType Container)) {
    throw "Verified standby snapshot not found: $SnapshotPath"
}
New-Item -ItemType Directory -Force -Path $DestinationRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $statusPath -Parent) | Out-Null

$startedAt = [DateTimeOffset]::UtcNow.ToString("o")
$output = & $python -m tools.isolated_restore_drill --snapshot $SnapshotPath --destination-root $DestinationRoot
$exitCode = $LASTEXITCODE
$outputText = ((@($output) -join "`n").Trim())

if ($exitCode -ne 0) {
    $failure = [ordered]@{
        schema = 1
        status = "error"
        message = "Isolated restore drill failed."
        started_at = $startedAt
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
        output = $outputText
    }
    $failure | ConvertTo-Json -Depth 8 | Set-Content -Path $statusPath -Encoding UTF8
    throw "Isolated restore drill failed."
}

try {
    $report = $outputText | ConvertFrom-Json
} catch {
    throw "Isolated restore drill returned invalid JSON."
}
if ($report.status -ne "ok" -or $report.activation_performed -ne $false -or $report.network_services_started -ne $false) {
    throw "Isolated restore drill did not confirm passive success."
}

$runDirectories = @(Get-ChildItem -Path $DestinationRoot -Directory | Sort-Object LastWriteTimeUtc -Descending)
$removedRuns = 0
if ($runDirectories.Count -gt $RetainRuns) {
    foreach ($oldRun in ($runDirectories | Select-Object -Skip $RetainRuns)) {
        Remove-Item -LiteralPath $oldRun.FullName -Recurse -Force
        $removedRuns++
    }
}

$status = [ordered]@{
    schema = 1
    status = "ok"
    message = "Isolated restore drill completed without activating the PC node."
    started_at = $startedAt
    completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    source_snapshot = $report.source_snapshot
    restored_snapshot = $report.restored_snapshot
    report_path = $report.report_path
    file_count = $report.file_count
    total_bytes = $report.total_bytes
    sqlite_checks = $report.sqlite_checks
    activation_performed = $false
    network_services_started = $false
    retained_runs = $RetainRuns
    removed_runs = $removedRuns
}
$status | ConvertTo-Json -Depth 8 | Set-Content -Path $statusPath -Encoding UTF8

Write-Output $outputText
Write-Host "Isolated restore drill completed without activating the PC node." -ForegroundColor Green
Write-Host "Restore drills: $DestinationRoot"
Write-Host "Latest status: $statusPath"
Write-Host "Retention: last $RetainRuns restore drills"
