param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHealthUrl = $env:SHARIPOVAI_VPS_HEALTH_URL,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

if ($VpsHealthUrl -and -not $Force) {
    try {
        $response = Invoke-WebRequest -Uri $VpsHealthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            throw "VPS is healthy. Refusing PC failover to prevent two active nodes. Use -Force only after intentionally disabling VPS services."
        }
    } catch {
        if ($_.Exception.Message -like "VPS is healthy*") { throw }
    }
}

$runtime = Join-Path $ProjectRoot "runtime"
$snapshot = Join-Path $runtime "remote_backups\current"
$data = Join-Path $ProjectRoot "data"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python environment not found. Run setup_pc.ps1 first." }
if (-not (Test-Path (Join-Path $snapshot "manifest.json"))) { throw "No verified VPS backup found. Run sync_vps_backup.ps1 first." }

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
    forced = [bool]$Force
} | ConvertTo-Json
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$marker | Set-Content (Join-Path $runtime "active_node.json") -Encoding UTF8

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1") -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw "PC Agent failed to start after restore." }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\windows\check_pc_node.ps1") -ProjectRoot $ProjectRoot -RequireManagedProcesses
if ($LASTEXITCODE -ne 0) { throw "PC failover health check failed." }

Write-Host "SharipovAI PC failover is active and verified." -ForegroundColor Green
