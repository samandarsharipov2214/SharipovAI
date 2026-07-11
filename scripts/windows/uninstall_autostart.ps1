$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$startup = [Environment]::GetFolderPath("Startup")
$names = @("SharipovAI PC Node.lnk", "SharipovAI Backup.lnk")
foreach ($name in $names) {
    $path = Join-Path $startup $name
    if (Test-Path $path) { Remove-Item $path -Force }
}
Write-Host "Автозапуск SharipovAI удалён для текущего пользователя." -ForegroundColor Green
