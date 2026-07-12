param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

function New-RandomSecret([int]$Bytes = 36) {
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($buffer).Replace("/", "_").Replace("+", "-").TrimEnd("=")
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python не найден. Установите Python 3.11+ и включите Add Python to PATH."
}

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $pythonCommand.Source -m venv (Join-Path $ProjectRoot ".venv")
}

& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Не удалось обновить pip в .venv" }
& $venvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Не удалось установить зависимости в .venv" }

$dataDir = Join-Path $ProjectRoot "data"
$runtimeDir = Join-Path $ProjectRoot "runtime"
$logsDir = Join-Path $runtimeDir "logs"
$backupDir = Join-Path $runtimeDir "backups"
New-Item -ItemType Directory -Force -Path $dataDir, $runtimeDir, $logsDir, $backupDir | Out-Null

$envFile = Join-Path $ProjectRoot ".env.local"
$credentialsFile = Join-Path $runtimeDir "initial_admin_credentials.txt"
if (-not (Test-Path $envFile)) {
    $authSecret = New-RandomSecret 48
    $adminPassword = New-RandomSecret 24
    $envLines = @(
        "SHARIPOVAI_ENV=local",
        "SHARIPOVAI_DATA_DIR=$dataDir",
        "SHARIPOVAI_BACKUP_DIR=$backupDir",
        "SHARIPOVAI_HOST=127.0.0.1",
        "SHARIPOVAI_PORT=8000",
        "SHARIPOVAI_DISABLE_AUTH=0",
        "AUTH_SECRET=$authSecret",
        "ADMIN_USERNAME=admin",
        "ADMIN_PASSWORD=$adminPassword",
        "FEATURE_BYBIT_WEBSOCKET=0",
        "EXCHANGE_LIVE_TRADING_ENABLED=0",
        "EXECUTION_KILL_SWITCH=1"
    )
    $envLines | Set-Content -Path $envFile -Encoding UTF8

    $credentialLines = @(
        "SharipovAI local admin",
        "Username: admin",
        "Password: $adminPassword",
        "",
        "Удалите этот файл после сохранения пароля в безопасном месте."
    )
    $credentialLines | Set-Content -Path $credentialsFile -Encoding UTF8
}

& $venvPython (Join-Path $ProjectRoot "tools\pc_node_backup.py") --source $dataDir --backup-root $backupDir --once
if ($LASTEXITCODE -ne 0) { throw "Первичная резервная копия не создана" }
& $venvPython -m pytest -q (Join-Path $ProjectRoot "tests\test_pc_node_backup.py")
if ($LASTEXITCODE -ne 0) { throw "Тест резервного копирования не пройден" }

Write-Host "SharipovAI PC node подготовлен." -ForegroundColor Green
Write-Host "Локальный env: $envFile"
if (Test-Path $credentialsFile) {
    Write-Host "Начальные данные администратора: $credentialsFile" -ForegroundColor Yellow
}
Write-Host "Для полного запуска: .\scripts\windows\bootstrap_pc_node.ps1 -SkipSetup"
