param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SnapshotPath = "",
    [string]$DestinationRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

if (-not $SnapshotPath) {
    $SnapshotPath = Join-Path $ProjectRoot "runtime\remote_backups\current"
}
if (-not $DestinationRoot) {
    $DestinationRoot = Join-Path $ProjectRoot "runtime\restore_drills"
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) {
    throw "Python environment not found. Run setup_pc.ps1 first."
}
if (-not (Test-Path $SnapshotPath -PathType Container)) {
    throw "Verified standby snapshot not found: $SnapshotPath"
}

& $python -m tools.isolated_restore_drill --snapshot $SnapshotPath --destination-root $DestinationRoot
if ($LASTEXITCODE -ne 0) {
    throw "Isolated restore drill failed."
}

Write-Host "Isolated restore drill completed without activating the PC node." -ForegroundColor Green
Write-Host "Restore drills: $DestinationRoot"
