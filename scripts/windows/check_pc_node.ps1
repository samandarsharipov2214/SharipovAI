param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$MaximumBackupAgeSeconds = 45,
    [switch]$RequireManagedProcesses
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

function Import-LocalEnv([string]$Path) {
    if (-not (Test-Path $Path)) { throw "Missing $Path. Run setup_pc.ps1 first." }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) { continue }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

function Test-ManagedProcess([string]$PidFile, [string]$Name, [System.Collections.Generic.List[string]]$Problems) {
    if (-not (Test-Path $PidFile)) {
        $Problems.Add("Missing PID file for ${Name}: $PidFile")
        return $false
    }
    try {
        $pidValue = [int](Get-Content $PidFile -Raw).Trim()
        $process = Get-Process -Id $pidValue -ErrorAction Stop
        Write-Host "[OK] $Name is running, PID=$($process.Id)"
        return $true
    } catch {
        $Problems.Add("Process $Name from PID file is not running: $($_.Exception.Message)")
        return $false
    }
}

function Test-AgentStatus([string]$StatusFile, [int]$MaximumAgeSeconds, [System.Collections.Generic.List[string]]$Problems) {
    if (-not (Test-Path $StatusFile)) {
        $Problems.Add("Missing PC Agent status: $StatusFile")
        return
    }
    try {
        $status = Get-Content $StatusFile -Raw | ConvertFrom-Json
        $updated = [DateTimeOffset]::Parse($status.updated_at)
        $age = ([DateTimeOffset]::UtcNow - $updated.ToUniversalTime()).TotalSeconds
        if ($age -gt $MaximumAgeSeconds) {
            $Problems.Add("PC Agent status is stale: $([math]::Round($age, 1)) sec.")
        }
        if (-not [bool]$status.web_healthy) {
            $Problems.Add("PC Agent reports unhealthy Dashboard")
        }
        if (-not [bool]$status.backup_healthy) {
            $Problems.Add("PC Agent reports unhealthy backup")
        }
        if ($status.last_error) {
            Write-Host "[WARN] PC Agent last error: $($status.last_error)" -ForegroundColor Yellow
        }
        if (($age -le $MaximumAgeSeconds) -and [bool]$status.web_healthy -and [bool]$status.backup_healthy) {
            Write-Host "[OK] PC Agent status is fresh: $([math]::Round($age, 1)) sec."
        }
    } catch {
        $Problems.Add("Could not read PC Agent status: $($_.Exception.Message)")
    }
}

Import-LocalEnv (Join-Path $ProjectRoot ".env.local")
$problems = New-Object System.Collections.Generic.List[string]
$dataDir = if ($env:SHARIPOVAI_DATA_DIR) { $env:SHARIPOVAI_DATA_DIR } else { Join-Path $ProjectRoot "data" }
$backupDir = if ($env:SHARIPOVAI_BACKUP_DIR) { $env:SHARIPOVAI_BACKUP_DIR } else { Join-Path $ProjectRoot "runtime\backups" }
$hostAddress = if ($env:SHARIPOVAI_HOST) { $env:SHARIPOVAI_HOST } else { "127.0.0.1" }
$port = if ($env:SHARIPOVAI_PORT) { $env:SHARIPOVAI_PORT } else { "8000" }

try {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $probe = Join-Path $dataDir ".pc-node-write-test"
    [DateTime]::UtcNow.ToString("o") | Set-Content -Path $probe -Encoding UTF8
    Remove-Item $probe -Force
    Write-Host "[OK] Data directory is writable"
} catch {
    $problems.Add("Data directory write check failed: $($_.Exception.Message)")
}

$manifestPath = Join-Path $backupDir "current\manifest.json"
try {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $created = [DateTimeOffset]::Parse($manifest.created_at)
    $age = ([DateTimeOffset]::UtcNow - $created.ToUniversalTime()).TotalSeconds
    if ($age -gt $MaximumBackupAgeSeconds) {
        $problems.Add("Backup is stale: $([math]::Round($age, 1)) sec.")
    } else {
        Write-Host "[OK] Backup is fresh: $([math]::Round($age, 1)) sec., files: $($manifest.file_count)"
    }
} catch {
    $problems.Add("Backup manifest check failed: $($_.Exception.Message)")
}

try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://$hostAddress`:$port/health" -TimeoutSec 5
    if ($response.StatusCode -ne 200) { throw "HTTP $($response.StatusCode)" }
    Write-Host "[OK] SharipovAI responds at http://$hostAddress`:$port"
} catch {
    $problems.Add("SharipovAI web node is not responding: $($_.Exception.Message)")
}

if ($RequireManagedProcesses) {
    $runtimeDir = Join-Path $ProjectRoot "runtime"
    $agentPid = Join-Path $runtimeDir "pids\pc_agent.pid"
    $agentStatus = Join-Path $runtimeDir "pc_agent_status.json"
    [void](Test-ManagedProcess $agentPid "PC Agent" $problems)
    Test-AgentStatus $agentStatus 90 $problems
}

$stderrLog = Join-Path $ProjectRoot "runtime\logs\pc_agent.stderr.log"
if ((Test-Path $stderrLog) -and (Get-Item $stderrLog).Length -gt 0) {
    Write-Host "[WARN] PC Agent stderr log contains data: $stderrLog" -ForegroundColor Yellow
}

if ($problems.Count -gt 0) {
    foreach ($problem in $problems) { Write-Host "[ERROR] $problem" -ForegroundColor Red }
    exit 1
}

Write-Host "All PC node checks passed." -ForegroundColor Green
exit 0
