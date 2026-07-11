param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$startup = [Environment]::GetFolderPath("Startup")
if (-not $startup) { throw "Windows Startup folder was not found." }

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$wsh = New-Object -ComObject WScript.Shell

$items = @(
    @{ Name = "SharipovAI PC Node.lnk"; Script = (Join-Path $ProjectRoot "scripts\windows\start_pc_node.ps1") },
    @{ Name = "SharipovAI Backup.lnk"; Script = (Join-Path $ProjectRoot "scripts\windows\start_backup.ps1") }
)

foreach ($item in $items) {
    if (-not (Test-Path $item.Script)) { throw "Startup script was not found: $($item.Script)" }
    $shortcutPath = Join-Path $startup $item.Name
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$($item.Script)`" -ProjectRoot `"$ProjectRoot`""
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = $item.Name.Replace(".lnk", "")
    $shortcut.Save()
}

Write-Host "SharipovAI autostart was installed for the current user." -ForegroundColor Green
Write-Host "Startup folder: $startup"
Write-Host "Start now: .\scripts\windows\start_pc_node.ps1"
Write-Host "Start backup now: .\scripts\windows\start_backup.ps1"
