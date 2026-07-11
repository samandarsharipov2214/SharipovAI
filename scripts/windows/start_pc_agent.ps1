param(
    [string]$ProjectRoot = "",
    [int]$StartupTimeoutSeconds = 65
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ProjectRoot) {
    $scriptDirectory = Split-Path -Parent $PSCommandPath
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory "..\.."))
}

Set-Location $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$agent = Join-Path $ProjectRoot "tools\pc_node_agent.py"
if (-not (Test-Path $python)) { throw "Python environment not found: $python" }
if (-not (Test-Path $agent)) { throw "PC agent not found: $agent" }

$runtimeDir = Join-Path $ProjectRoot "runtime"
$logsDir = Join-Path $runtimeDir "logs"
$pidsDir = Join-Path $runtimeDir "pids"
New-Item -ItemType Directory -Force -Path $runtimeDir, $logsDir, $pidsDir | Out-Null

$pidFile = Join-Path $pidsDir "pc_agent.pid"
$statusFile = Join-Path $runtimeDir "pc_agent_status.json"
$outLog = Join-Path $logsDir "pc_agent.stdout.log"
$errLog = Join-Path $logsDir "pc_agent.stderr.log"

function Get-LiveProcess([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    try {
        $pidValue = [int](Get-Content $Path -Raw).Trim()
        return Get-Process -Id $pidValue -ErrorAction Stop
    } catch {
        Remove-Item $Path -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Test-AgentHealthy([string]$Path, [int]$MaximumAgeSeconds = 60) {
    if (-not (Test-Path $Path)) { return $false }
    try {
        $status = Get-Content $Path -Raw | ConvertFrom-Json
        $updated = [DateTimeOffset]::Parse($status.updated_at)
        $age = ([DateTimeOffset]::UtcNow - $updated.ToUniversalTime()).TotalSeconds
        return ($age -le $MaximumAgeSeconds) -and [bool]$status.web_healthy -and [bool]$status.backup_healthy
    } catch {
        return $false
    }
}

function Rotate-Log([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    Move-Item $Path "$Path.$timestamp" -Force
}

$existing = Get-LiveProcess $pidFile
if ($existing) {
    if (Test-AgentHealthy $statusFile 75) {
        Write-Host "SharipovAI PC Agent is already healthy. PID=$($existing.Id)" -ForegroundColor Green
        exit 0
    }
    try { Stop-Process -Id $existing.Id -Force -ErrorAction Stop } catch { }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

if (Test-AgentHealthy $statusFile 45) {
    Write-Host "SharipovAI PC Agent is already healthy; duplicate launch was skipped." -ForegroundColor Yellow
    exit 0
}

Rotate-Log $outLog
Rotate-Log $errLog
$argumentLine = "`"$agent`" --project-root `"$ProjectRoot`""
$process = Start-Process -FilePath $python -ArgumentList $argumentLine -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
$process.Id | Set-Content -Path $pidFile -Encoding ASCII

$deadline = [DateTimeOffset]::UtcNow.AddSeconds([Math]::Max($StartupTimeoutSeconds, 20))
do {
    Start-Sleep -Seconds 1
    if ($process.HasExited) { break }
    if (Test-AgentHealthy $statusFile 75) {
        Write-Host "SharipovAI PC Agent started and verified. PID=$($process.Id)" -ForegroundColor Green
        exit 0
    }
} while ([DateTimeOffset]::UtcNow -lt $deadline)

try {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
} catch { }
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
throw "SharipovAI PC Agent did not become healthy. Check $errLog and $statusFile"
