param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [int]$MaximumBackupAgeSeconds = 45,
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
        $Problems.Add("Не найден PID-файл процесса ${Name}: $PidFile")
        return $false
    }
    try {
        $pidValue = [int](Get-Content $PidFile -Raw).Trim()
        $process = Get-Process -Id $pidValue -ErrorAction Stop
        Write-Host "[OK] $Name запущен, PID=$($process.Id)"
        return $true
    } catch {
        $Problems.Add("Процесс $Name из PID-файла не работает: $($_.Exception.Message)")
        return $false
    }
}

function Test-AgentStatus([string]$StatusFile, [int]$MaximumAgeSeconds, [System.Collections.Generic.List[string]]$Problems) {
    if (-not (Test-Path $StatusFile)) {
        $Problems.Add("Не найден статус PC Agent: $StatusFile")
        return
    }
    try {
        $status = Get-Content $StatusFile -Raw | ConvertFrom-Json
        $updated = [DateTimeOffset]::Parse($status.updated_at)
        $age = ([DateTimeOffset]::UtcNow - $updated.ToUniversalTime()).TotalSeconds
        if ($age -gt $MaximumAgeSeconds) {
            $Problems.Add("Статус PC Agent устарел: $([math]::Round($age, 1)) сек.")
        }
        if (-not [bool]$status.web_healthy) {
            $Problems.Add("PC Agent сообщает: Dashboard нездоров")
        }
        if (-not [bool]$status.backup_healthy) {
            $Problems.Add("PC Agent сообщает: backup нездоров")
        }
        if ($status.last_error) {
            Write-Host "[WARN] Последняя ошибка PC Agent: $($status.last_error)" -ForegroundColor Yellow
        }
        if (($age -le $MaximumAgeSeconds) -and [bool]$status.web_healthy -and [bool]$status.backup_healthy) {
            Write-Host "[OK] PC Agent status свежий: $([math]::Round($age, 1)) сек."
        }
    } catch {
        $Problems.Add("Не удалось прочитать статус PC Agent: $($_.Exception.Message)")
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
    $runtimeDir = Join-Path $ProjectRoot "runtime"
    $agentPid = Join-Path $runtimeDir "pids\pc_agent.pid"
    $agentStatus = Join-Path $runtimeDir "pc_agent_status.json"
    [void](Test-ManagedProcess $agentPid "PC Agent" $problems)
    Test-AgentStatus $agentStatus 90 $problems
}

$stderrLog = Join-Path $ProjectRoot "runtime\logs\pc_agent.stderr.log"
if ((Test-Path $stderrLog) -and (Get-Item $stderrLog).Length -gt 0) {
    Write-Host "[WARN] В stderr-журнале PC Agent есть данные: $stderrLog" -ForegroundColor Yellow
}

if ($problems.Count -gt 0) {
    foreach ($problem in $problems) { Write-Host "[ERROR] $problem" -ForegroundColor Red }
    exit 1
}

Write-Host "Все проверки PC node пройдены." -ForegroundColor Green
exit 0
