param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$StartupTimeoutSeconds = 35
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

function Test-Health([string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
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

Import-LocalEnv (Join-Path $ProjectRoot ".env.local")
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python virtual environment was not found. Run setup_pc.ps1 first." }

$runtimeDir = Join-Path $ProjectRoot "runtime"
$logsDir = Join-Path $runtimeDir "logs"
$pidsDir = Join-Path $runtimeDir "pids"
New-Item -ItemType Directory -Force -Path $runtimeDir, $logsDir, $pidsDir | Out-Null

$hostAddress = if ($env:SHARIPOVAI_HOST) { $env:SHARIPOVAI_HOST } else { "127.0.0.1" }
$port = if ($env:SHARIPOVAI_PORT) { $env:SHARIPOVAI_PORT } else { "8000" }
$healthUrl = "http://$hostAddress`:$port/health"
$pidFile = Join-Path $pidsDir "pc_node.pid"
$statusFile = Join-Path $runtimeDir "pc_node_status.json"
$outLog = Join-Path $logsDir "pc_node.stdout.log"
$errLog = Join-Path $logsDir "pc_node.stderr.log"

$existing = Get-LiveProcessFromPidFile $pidFile
if ($existing) {
    if (Test-Health $healthUrl) {
        Write-Host "SharipovAI PC node is already running. PID=$($existing.Id)" -ForegroundColor Green
        exit 0
    }
    try { Stop-Process -Id $existing.Id -Force -ErrorAction Stop } catch { }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

if (Test-Health $healthUrl) {
    [ordered]@{
        status = "already_responding"
        url = $healthUrl
        checked_at = [DateTimeOffset]::UtcNow.ToString("o")
    } | ConvertTo-Json | Set-Content -Path $statusFile -Encoding UTF8
    Write-Host "SharipovAI already responds at $healthUrl; duplicate process was not started." -ForegroundColor Yellow
    exit 0
}

Rotate-Log $outLog
Rotate-Log $errLog

$arguments = @(
    "-m", "uvicorn", "dashboard:app",
    "--host", $hostAddress,
    "--port", [string]$port
)
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
$process.Id | Set-Content -Path $pidFile -Encoding ASCII

$deadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max($StartupTimeoutSeconds, 5))
do {
    Start-Sleep -Milliseconds 750
    if ($process.HasExited) {
        break
    }
    if (Test-Health $healthUrl) {
        [ordered]@{
            status = "running"
            pid = $process.Id
            url = $healthUrl
            started_at = [DateTimeOffset]::UtcNow.ToString("o")
            stdout_log = $outLog
            stderr_log = $errLog
        } | ConvertTo-Json | Set-Content -Path $statusFile -Encoding UTF8
        Write-Host "SharipovAI PC node started. PID=$($process.Id), URL=$healthUrl" -ForegroundColor Green
        exit 0
    }
} while ([DateTimeOffset]::UtcNow -lt $deadline)

try {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
} catch { }
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
[ordered]@{
    status = "failed"
    url = $healthUrl
    failed_at = [DateTimeOffset]::UtcNow.ToString("o")
    stderr_log = $errLog
} | ConvertTo-Json | Set-Content -Path $statusFile -Encoding UTF8
throw "SharipovAI PC node did not become healthy. Check $errLog"
