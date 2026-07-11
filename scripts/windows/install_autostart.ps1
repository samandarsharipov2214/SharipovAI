param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$startup = [Environment]::GetFolderPath("Startup")
if (-not $startup) { throw "Не удалось определить папку автозагрузки Windows." }

$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$wsh = New-Object -ComObject WScript.Shell

$items = @(
    @{ Name = "SharipovAI PC Node.lnk"; Script = (Join-Path $ProjectRoot "scripts\windows\start_pc_node.ps1") },
    @{ Name = "SharipovAI Backup.lnk"; Script = (Join-Path $ProjectRoot "scripts\windows\start_backup.ps1") }
)

foreach ($item in $items) {
    if (-not (Test-Path $item.Script)) { throw "Не найден файл запуска: $($item.Script)" }
    $shortcutPath = Join-Path $startup $item.Name
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$($item.Script)`" -ProjectRoot `"$ProjectRoot`""
    $shortcut.WorkingDirectory = $ProjectRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = $item.Name.Replace(".lnk", "")
    $shortcut.Save()
}

Write-Host "Автозапуск SharipovAI установлен для текущего пользователя." -ForegroundColor Green
Write-Host "Папка автозагрузки: $startup"
Write-Host "Запуск сейчас: .\scripts\windows\start_pc_node.ps1"
Write-Host "Резервирование сейчас: .\scripts\windows\start_backup.ps1"
