param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$MaximumBackupAgeSeconds = 30,
    [switch]$RequireManagedProcesses
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

function Test-ManagedProcess([string]$PidFile, [string]$Name, [System.Collections.Generic.List[string]]$Problems) {
    if (-not (Test-Path $PidFile)) {
        $Problems.Add("Не найден PID-файл процесса $Name: $PidFile")
        return
    }
    try {
        $pidValue = [int](Get-Content $PidFile -Raw).Trim()
        $process = Get-Process -Id $pidValue -ErrorAction Stop
        Write-Host "[OK] $Name запущен, PID=$($process.Id)"
    } catch {
        $Problems.Add("Процесс $Name из PID-файла не работает: $($_.Exception.Message)")
    }
}

Import-LocalEnv (Join-Path $ProjectRoot ".env.local")
$problems = New-Object System.Collections.Generic.List[string]
$dataDir = if ($env:SHARIPOVAI_DATA_DIR) { $env:SHARIPOVAI_DATA_DIR } else { Join-Path $ProjectRoot "data" }
$backupDir = if ($env:SHARIPOVAI_BACKUP_DIR) { $env:SHARIPOVAI_BACKUP_DIR } else { Join-Path $ProjectRoot "runtime\backups" }
$hostAddress = if ($env:SHARIPOVAI_HOST) { $env:SHARIPOVAI_HOST } else { "127.0.0.1" }
$port = if ($env:SHARIPOVAI_PORT) { $env:SHARIPOVAI_PORT } else { "8000" }

try {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $probe = Join-Path $dataDir ".pc-node-write-test"
    [DateTime]::UtcNow.ToString("o") | Set-Content -Path $probe -Encoding UTF8
    Remove-Item $probe -Force
    Write-Host "[OK] Запись в data доступна"
} catch {
    $problems.Add("Нет безопасной записи в data: $($_.Exception.Message)")
}

$manifestPath = Join-Path $backupDir "current\manifest.json"
try {
    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    $created = [DateTimeOffset]::Parse($manifest.created_at)
    $age = ([DateTimeOffset]::UtcNow - $created.ToUniversalTime()).TotalSeconds
    if ($age -gt $MaximumBackupAgeSeconds) {
        $problems.Add("Резервная копия устарела: $([math]::Round($age, 1)) сек.")
    } else {
        Write-Host "[OK] Резервная копия свежая: $([math]::Round($age, 1)) сек., файлов: $($manifest.file_count)"
    }
} catch {
    $problems.Add("Не удалось проверить backup manifest: $($_.Exception.Message)")
}

try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://$hostAddress`:$port/health" -TimeoutSec 5
    if ($response.StatusCode -ne 200) { throw "HTTP $($response.StatusCode)" }
    Write-Host "[OK] SharipovAI отвечает: http://$hostAddress`:$port"
} catch {
    $problems.Add("SharipovAI web node не отвечает: $($_.Exception.Message)")
}

if ($RequireManagedProcesses) {
    $pidsDir = Join-Path $ProjectRoot "runtime\pids"
    Test-ManagedProcess (Join-Path $pidsDir "pc_node.pid") "PC Node" $problems
    Test-ManagedProcess (Join-Path $pidsDir "backup.pid") "Backup" $problems
}

$stderrLog = Join-Path $ProjectRoot "runtime\logs\pc_node.stderr.log"
if (Test-Path $stderrLog) {
    $errorSize = (Get-Item $stderrLog).Length
    if ($errorSize -gt 0) {
        Write-Host "[WARN] В stderr-журнале есть данные: $stderrLog" -ForegroundColor Yellow
    }
}

if ($problems.Count -gt 0) {
    foreach ($problem in $problems) { Write-Host "[ERROR] $problem" -ForegroundColor Red }
    exit 1
}

Write-Host "Все проверки PC node пройдены." -ForegroundColor Green
exit 0
