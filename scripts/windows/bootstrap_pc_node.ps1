param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [switch]$SkipSetup,
    [switch]$SkipAutostart
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
        Invoke-Step "AUTOSTART" (Join-Path $ProjectRoot "scripts\windows\install_autostart.ps1") @("-ProjectRoot", $ProjectRoot)
    }

    Invoke-Step "PC AGENT" (Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1") @("-ProjectRoot", $ProjectRoot)
    Invoke-Step "HEALTH CHECK" (Join-Path $ProjectRoot "scripts\windows\check_pc_node.ps1") @("-ProjectRoot", $ProjectRoot, "-RequireManagedProcesses")

    [ordered]@{
        status = "ok"
        project_root = $ProjectRoot
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
        autostart_installed = -not $SkipAutostart
        setup_executed = -not $SkipSetup
        supervisor = "PC Agent"
        agent_status = (Join-Path $runtimeDir "pc_agent_status.json")
        dashboard_url = "http://127.0.0.1:8000/"
        health_url = "http://127.0.0.1:8000/health"
    } | ConvertTo-Json | Set-Content -Path $reportPath -Encoding UTF8

    Write-Host "SharipovAI PC Node установлен и проверен." -ForegroundColor Green
    Write-Host "Dashboard: http://127.0.0.1:8000/"
    Write-Host "Отчёт: $reportPath"
    exit 0
} catch {
    [ordered]@{
        status = "error"
        project_root = $ProjectRoot
        failed_at = [DateTimeOffset]::UtcNow.ToString("o")
        error = $_.Exception.Message
    } | ConvertTo-Json | Set-Content -Path $reportPath -Encoding UTF8
    Write-Host "PC Node installation failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Отчёт: $reportPath"
    exit 1
}
