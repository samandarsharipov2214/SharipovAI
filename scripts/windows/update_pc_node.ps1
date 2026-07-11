param(
    [Parameter(Mandatory = $true)]
    [string]$Archive,
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$archivePath = (Resolve-Path $Archive).Path
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$updater = Join-Path $ProjectRoot "tools\pc_node_update.py"

if (-not (Test-Path $python)) {
    throw "Python environment not found: $python"
}
if (-not (Test-Path $updater)) {
    throw "Updater not found: $updater"
}

Write-Host "Stopping SharipovAI processes before update..."
Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        ($_.CommandLine -like "*$ProjectRoot*") -and
        (($_.CommandLine -like "*uvicorn*") -or ($_.CommandLine -like "*pc_node_backup.py*"))
    } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { }
    }

& $python $updater --archive $archivePath --project-root $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "SharipovAI update failed. Previous code was restored automatically."
}

$utf8Bom = New-Object System.Text.UTF8Encoding($true)
Get-ChildItem (Join-Path $ProjectRoot "scripts\windows\*.ps1") -File | ForEach-Object {
    $text = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($_.FullName, $text, $utf8Bom)
}

Write-Host "Starting SharipovAI PC node and backup..."
Start-Process powershell.exe -WorkingDirectory $ProjectRoot -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\windows\start_pc_node.ps1`" -ProjectRoot `"$ProjectRoot`""
Start-Process powershell.exe -WorkingDirectory $ProjectRoot -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ProjectRoot\scripts\windows\start_backup.ps1`" -ProjectRoot `"$ProjectRoot`""

Start-Sleep -Seconds 8
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\windows\check_pc_node.ps1") -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "Update was installed, but the final PC node health check failed."
}

Write-Host "SharipovAI update and verification completed." -ForegroundColor Green
