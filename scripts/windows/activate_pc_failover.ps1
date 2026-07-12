param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHealthUrl = $env:SHARIPOVAI_VPS_HEALTH_URL,
    [int]$MaximumBackupAgeSeconds = $(if ($env:SHARIPOVAI_STANDBY_MAX_BACKUP_AGE_SECONDS) { [int]$env:SHARIPOVAI_STANDBY_MAX_BACKUP_AGE_SECONDS } else { 7200 }),
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

if (-not $Force) {
    throw "PC failover requires explicit -Force confirmation after the operator has disabled VPS services."
}
if (-not $VpsHealthUrl) {
    throw "VPS health URL is required; refusing failover without a split-brain check."
}
$healthUri = $null
if (-not [Uri]::TryCreate($VpsHealthUrl, [UriKind]::Absolute, [ref]$healthUri) -or
    $healthUri.Scheme -ne "https" -or
    $healthUri.UserInfo -or
    $healthUri.AbsolutePath -ne "/health") {
    throw "VPS health URL must be an HTTPS /health endpoint without user information."
}

try {
    $response = Invoke-WebRequest -Uri $healthUri.AbsoluteUri -UseBasicParsing -TimeoutSec 5
    throw "VPS responded with HTTP $($response.StatusCode). Refusing PC failover to prevent two active nodes."
} catch {
    if ($_.Exception.Message -like "VPS responded with HTTP*") { throw }
    if ($_.Exception.Response) {
        throw "VPS is reachable and returned an HTTP response. Refusing PC failover to prevent two active nodes."
    }
    Write-Host "[WARN] VPS health endpoint is unreachable. Explicit failover confirmation accepted." -ForegroundColor Yellow
}

$runtime = Join-Path $ProjectRoot "runtime"
$snapshot = Join-Path $runtime "remote_backups\current"
$data = Join-Path $ProjectRoot "data"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$reporter = Join-Path $ProjectRoot "tools\standby_health_report.py"
if (-not (Test-Path $python)) { throw "Python environment not found. Run setup_pc.ps1 first." }
if (-not (Test-Path (Join-Path $snapshot "manifest.json"))) { throw "No verified VPS backup found. Run sync_vps_backup.ps1 first." }

# Force confirms the operator action; it never bypasses stale or invalid backup protection.
& $python $reporter --project-root $ProjectRoot --maximum-age-seconds $MaximumBackupAgeSeconds
if ($LASTEXITCODE -ne 0) {
    $healthPath = Join-Path $runtime "standby_health.json"
    $reason = "standby health report unavailable"
    if (Test-Path $healthPath) {
        $health = Get-Content $healthPath -Raw | ConvertFrom-Json
        $reason = "$($health.status): $($health.reasons -join '; ')"
    }
    throw "PC failover blocked because standby is not READY. $reason"
}

# Stop only SharipovAI processes whose command line points to this project directory.
$escapedRoot = [Regex]::Escape($ProjectRoot)
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match $escapedRoot -and
    ($_.CommandLine -match "pc_node_agent.py|pc_node_backup.py|uvicorn")
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

& $python (Join-Path $ProjectRoot "tools\restore_verified_backup.py") --snapshot $snapshot --destination $data
if ($LASTEXITCODE -ne 0) { throw "Verified restore failed; PC node was not started." }

$marker = [ordered]@{
    active_node = "pc"
    activated_at = [DateTimeOffset]::UtcNow.ToString("o")
    source = "verified_vps_backup"
    forced = $true
    operator_confirmed_vps_disabled = $true
    vps_health_url = $healthUri.AbsoluteUri
    maximum_backup_age_seconds = $MaximumBackupAgeSeconds
} | ConvertTo-Json
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$marker | Set-Content (Join-Path $runtime "active_node.json") -Encoding UTF8

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1") -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "PC Agent failed to start after restore." }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\windows\check_pc_node.ps1") -ProjectRoot $ProjectRoot -RequireManagedProcesses
if ($LASTEXITCODE -ne 0) { throw "PC failover health check failed." }

Write-Host "SharipovAI PC failover is active and verified." -ForegroundColor Green
