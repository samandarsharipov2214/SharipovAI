param(
    [string]$ProjectRoot = "",
    [switch]$EnableActiveNode
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ProjectRoot) {
    $scriptDirectory = Split-Path -Parent $PSCommandPath
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory "..\.."))
}

$startup = [Environment]::GetFolderPath("Startup")
if (-not $startup) { throw "Windows Startup folder was not found." }

$shortcutPath = Join-Path $startup "SharipovAI PC Agent.lnk"
$legacyNames = @("SharipovAI PC Node.lnk", "SharipovAI Backup.lnk", "SharipovAI PC Agent.lnk")
foreach ($name in $legacyNames) {
    $legacyPath = Join-Path $startup $name
    if (Test-Path $legacyPath) { Remove-Item $legacyPath -Force }
}

if (-not $EnableActiveNode) {
    Write-Host "SharipovAI PC node remains passive. Active-node autostart is disabled." -ForegroundColor Green
    Write-Host "Use install_vps_backup_sync.ps1 for passive backup synchronization."
    exit 0
}

$agentScript = Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1"
if (-not (Test-Path $agentScript)) { throw "PC agent launcher was not found: $agentScript" }
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershell
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$agentScript`" -ProjectRoot `"$ProjectRoot`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "SharipovAI active PC node agent"
$shortcut.Save()

Write-Host "SharipovAI active PC Agent autostart installed." -ForegroundColor Yellow
Write-Host "Startup shortcut: $shortcutPath"
