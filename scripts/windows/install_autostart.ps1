param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ProjectRoot) {
    $scriptDirectory = Split-Path -Parent $PSCommandPath
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory "..\.."))
}

$startup = [Environment]::GetFolderPath("Startup")
if (-not $startup) { throw "Windows Startup folder was not found." }

$agentScript = Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1"
if (-not (Test-Path $agentScript)) { throw "PC agent launcher was not found: $agentScript" }

$legacyNames = @("SharipovAI PC Node.lnk", "SharipovAI Backup.lnk")
foreach ($name in $legacyNames) {
    $legacyPath = Join-Path $startup $name
    if (Test-Path $legacyPath) { Remove-Item $legacyPath -Force }
}

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$shortcutPath = Join-Path $startup "SharipovAI PC Agent.lnk"
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powershell
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$agentScript`" -ProjectRoot `"$ProjectRoot`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "SharipovAI PC Agent"
$shortcut.Save()

Write-Host "SharipovAI PC Agent autostart installed." -ForegroundColor Green
Write-Host "Startup shortcut: $shortcutPath"
