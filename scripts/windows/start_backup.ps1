param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$IntervalSeconds = 10
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

function Import-LocalEnv([string]$Path) {
    if (-not (Test-Path $Path)) { throw "Не найден $Path. Сначала запустите setup_pc.ps1." }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) { continue }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

Import-LocalEnv (Join-Path $ProjectRoot ".env.local")
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Виртуальное окружение не найдено. Сначала запустите setup_pc.ps1." }

$dataDir = if ($env:SHARIPOVAI_DATA_DIR) { $env:SHARIPOVAI_DATA_DIR } else { Join-Path $ProjectRoot "data" }
$backupDir = if ($env:SHARIPOVAI_BACKUP_DIR) { $env:SHARIPOVAI_BACKUP_DIR } else { Join-Path $ProjectRoot "runtime\backups" }

& $python (Join-Path $ProjectRoot "tools\pc_node_backup.py") --source $dataDir --backup-root $backupDir --interval $IntervalSeconds
exit $LASTEXITCODE
