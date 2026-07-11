param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$IntervalSeconds = 10,
    [int]$StartupTimeoutSeconds = 25
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

function Import-LocalEnv([string]$Path) {
    if (-not (Test-Path $Path)) { throw "File not found: $Path. Run setup_pc.ps1 first." }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) { continue }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

function Get-LiveProcessFromPidFile([string]$PidFile) {
    if (-not (Test-Path $PidFile)) { return $null }
    try {
        $pidValue = [int](Get-Content $PidFile -Raw).Trim()
        return Get-Process -Id $pidValue -ErrorAction Stop
    } catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Rotate-Log([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Move-Item $Path "$Path.$timestamp" -Force
}

function Test-FreshManifest([string]$ManifestPath, [int]$MaximumAgeSeconds) {
    if (-not (Test-Path $ManifestPath)) { return $false }
    try {
        $manifest = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $created = [DateTimeOffset]::Parse($manifest.created_at)
        $age = ([DateTimeOffset]::UtcNow - $created.ToUniversalTime()).TotalSeconds
        return $age -le $MaximumAgeSeconds
    } catch {
        return $false
    }
}

Import-LocalEnv (Join-Path $ProjectRoot ".env.local")
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python virtual environment was not found. Run setup_pc.ps1 first." }

$runtimeDir = Join-Path $ProjectRoot "runtime"
$logsDir = Join-Path $runtimeDir "logs"
$pidsDir = Join-Path $runtimeDir "pids"
New-Item -ItemType Directory -Force -Path $runtimeDir, $logsDir, $pidsDir | Out-Null

$dataDir = if ($env:SHARIPOVAI_DATA_DIR) { $env:SHARIPOVAI_DATA_DIR } else { Join-Path $ProjectRoot "data" }
$backupDir = if ($env:SHARIPOVAI_BACKUP_DIR) { $env:SHARIPOVAI_BACKUP_DIR } else { Join-Path $ProjectRoot "runtime\backups" }
New-Item -ItemType Directory -Force -Path $dataDir, $backupDir | Out-Null

$pidFile = Join-Path $pidsDir "backup.pid"
$statusFile = Join-Path $runtimeDir "backup_status.json"
$outLog = Join-Path $logsDir "backup.stdout.log"
$errLog = Join-Path $logsDir "backup.stderr.log"
$manifestPath = Join-Path $backupDir "current\manifest.json"

$existing = Get-LiveProcessFromPidFile $pidFile
if ($existing) {
    $maxAge = [Math]::Max($IntervalSeconds * 3, 30)
    if (Test-FreshManifest $manifestPath $maxAge) {
        Write-Host "SharipovAI backup loop is already running. PID=$($existing.Id)" -ForegroundColor Green
        exit 0
    }
    try { Stop-Process -Id $existing.Id -Force -ErrorAction Stop } catch { }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Rotate-Log $outLog
Rotate-Log $errLog

$backupTool = Join-Path $ProjectRoot "tools\pc_node_backup.py"
$arguments = @(
    $backupTool,
    "--source", $dataDir,
    "--backup-root", $backupDir,
    "--interval", [string]([Math]::Max($IntervalSeconds, 1))
)
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
$process.Id | Set-Content -Path $pidFile -Encoding ASCII

$deadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max($StartupTimeoutSeconds, 5))
do {
    Start-Sleep -Milliseconds 750
    if ($process.HasExited) {
        break
    }
    if (Test-FreshManifest $manifestPath ([Math]::Max($IntervalSeconds * 3, 30))) {
        [ordered]@{
            status = "running"
            pid = $process.Id
            interval_seconds = $IntervalSeconds
            manifest = $manifestPath
            started_at = [DateTimeOffset]::UtcNow.ToString("o")
            stdout_log = $outLog
            stderr_log = $errLog
        } | ConvertTo-Json | Set-Content -Path $statusFile -Encoding UTF8
        Write-Host "SharipovAI backup loop started. PID=$($process.Id)" -ForegroundColor Green
        exit 0
    }
} while ([DateTimeOffset]::UtcNow -lt $deadline)

try {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
} catch { }
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
[ordered]@{
    status = "failed"
    failed_at = [DateTimeOffset]::UtcNow.ToString("o")
    stderr_log = $errLog
} | ConvertTo-Json | Set-Content -Path $statusFile -Encoding UTF8
throw "SharipovAI backup loop did not become healthy. Check $errLog"
