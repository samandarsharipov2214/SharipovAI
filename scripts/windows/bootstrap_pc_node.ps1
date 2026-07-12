param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [switch]$SkipSetup,
    [switch]$SkipAutostart,
    [switch]$Activate
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

$runtimeDir = Join-Path $ProjectRoot "runtime"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$reportPath = Join-Path $runtimeDir "pc_node_installation.json"

function Invoke-Step([string]$Name, [string]$Script, [string[]]$Arguments = @()) {
    Write-Host "[$Name]" -ForegroundColor Cyan
    if (-not (Test-Path $Script)) { throw "Script not found: $Script" }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Script @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

try {
    if (-not $SkipSetup) {
        Invoke-Step "SETUP" (Join-Path $ProjectRoot "scripts\windows\setup_pc.ps1") @("-ProjectRoot", $ProjectRoot)
    }

    if (-not $SkipAutostart) {
        $autostartArgs = @("-ProjectRoot", $ProjectRoot)
        if ($Activate) { $autostartArgs += "-EnableActiveNode" }
        Invoke-Step "AUTOSTART" (Join-Path $ProjectRoot "scripts\windows\install_autostart.ps1") $autostartArgs
    }

    if ($Activate) {
        Invoke-Step "PC AGENT" (Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1") @("-ProjectRoot", $ProjectRoot)
        Invoke-Step "HEALTH CHECK" (Join-Path $ProjectRoot "scripts\windows\check_pc_node.ps1") @("-ProjectRoot", $ProjectRoot, "-RequireManagedProcesses")
    }

    [ordered]@{
        status = "ok"
        project_root = $ProjectRoot
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
        autostart_installed = (-not $SkipAutostart) -and [bool]$Activate
        setup_executed = -not $SkipSetup
        mode = $(if ($Activate) { "active" } else { "standby" })
        supervisor = $(if ($Activate) { "PC Agent" } else { "disabled_until_failover" })
        agent_status = (Join-Path $runtimeDir "pc_agent_status.json")
        dashboard_url = $(if ($Activate) { "http://127.0.0.1:8000/" } else { $null })
        health_url = $(if ($Activate) { "http://127.0.0.1:8000/health" } else { $null })
    } | ConvertTo-Json | Set-Content -Path $reportPath -Encoding UTF8

    if ($Activate) {
        Write-Host "SharipovAI PC Node installed, activated and verified." -ForegroundColor Yellow
    } else {
        Write-Host "SharipovAI PC Node prepared as passive standby." -ForegroundColor Green
        Write-Host "Install verified VPS synchronization with install_vps_backup_sync.ps1."
        Write-Host "Activate only during an outage with activate_pc_failover.ps1."
    }
    Write-Host "Report: $reportPath"
    exit 0
} catch {
    [ordered]@{
        status = "error"
        project_root = $ProjectRoot
        failed_at = [DateTimeOffset]::UtcNow.ToString("o")
        error = $_.Exception.Message
    } | ConvertTo-Json | Set-Content -Path $reportPath -Encoding UTF8
    Write-Host "PC Node installation failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Report: $reportPath"
    exit 1
}
