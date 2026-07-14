param(
    [string]$ProjectRoot = "D:\SharipovAI_Server\SharipovAI",
    [string]$BaselineCommit = "54d6223dbe475a0a9dfc7893bef76fef15f35b69"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Read-EnvFile {
    param([string]$Path)
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = ([string]$raw).Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1]
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Stop-SharipovAI {
    param([string]$Root)

    $pids = New-Object System.Collections.Generic.HashSet[int]
    try {
        foreach ($connection in @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
            [void]$pids.Add([int]$connection.OwningProcess)
        }
    } catch {}

    try {
        foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
            $command = [string]$process.CommandLine
            if (-not $command) { continue }
            if ($command.Contains("pc_node_agent.py") -or
                $command.Contains("pc_node_backup.py") -or
                ($command.Contains("uvicorn") -and $command.Contains("dashboard:app"))) {
                [void]$pids.Add([int]$process.ProcessId)
            }
        }
    } catch {}

    $pidFile = Join-Path $Root "runtime\pids\pc_agent.pid"
    if (Test-Path -LiteralPath $pidFile) {
        try { [void]$pids.Add([int](Get-Content -LiteralPath $pidFile -Raw).Trim()) } catch {}
    }

    foreach ($processId in $pids) {
        if ($processId -gt 0 -and $processId -ne $PID) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
    }

    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $Root "runtime\pc_agent_status.json") -Force -ErrorAction SilentlyContinue

    $deadline = (Get-Date).AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
        if (-not $listener) { return }
    } while ((Get-Date) -lt $deadline)

    throw "Port 8000 is still occupied after stopping SharipovAI."
}

function Start-SharipovAI {
    param([string]$Root)

    $startScript = Join-Path $Root "scripts\windows\start_pc_agent.ps1"
    if (-not (Test-Path -LiteralPath $startScript)) {
        throw "Start script not found: $startScript"
    }

    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -NoLogo -NoProfile -ExecutionPolicy Bypass `
        -File $startScript -ProjectRoot $Root
    if ($LASTEXITCODE -ne 0) {
        throw "PC Agent failed to start. Check runtime\logs\pc_agent.stderr.log"
    }

    $deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Seconds 2
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5
            if ($health.status -eq "ok") { return }
        } catch {}
    } while ((Get-Date) -lt $deadline)

    throw "SharipovAI did not pass /health after UI restore."
}

function Assert-VerifiedWeb2Files {
    param([string]$Root)

    $web2 = Join-Path $Root "dashboard\static\web2"
    $indexPath = Join-Path $web2 "index.html"
    $overviewPath = Join-Path $web2 "overview_runtime_v25.js"
    $coordinatorPath = Join-Path $web2 "navigation_coordinator_v23.js"
    $tradingViewPath = Join-Path $web2 "tradingview_market_v32.js"
    $heightFixPath = Join-Path $web2 "tradingview_widget_height_fix_v34.js"
    $hostPath = Join-Path $Root "dashboard\web2_host.py"

    foreach ($path in @($indexPath, $overviewPath, $coordinatorPath, $tradingViewPath, $heightFixPath, $hostPath)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required restored file is missing: $path" }
    }

    $index = Get-Content -LiteralPath $indexPath -Raw
    $overview = Get-Content -LiteralPath $overviewPath -Raw
    $coordinator = Get-Content -LiteralPath $coordinatorPath -Raw
    $tradingView = Get-Content -LiteralPath $tradingViewPath -Raw
    $heightFix = Get-Content -LiteralPath $heightFixPath -Raw
    $host = Get-Content -LiteralPath $hostPath -Raw

    if ($index -notmatch "SharipovAI OS") { throw "Restored shell title is not SharipovAI OS." }
    if ($index -match "sections_v10\.js") { throw "Obsolete overview renderer is still loaded." }
    if ($overview -notmatch "Размер позиции" -or $overview -notmatch "Чистый результат") {
        throw "Transparent PnL cards are missing from the restored overview."
    }
    if ($coordinator -notmatch "const VERSION = 31") { throw "Web2 ownership coordinator v31 is missing." }
    if ($tradingView -notmatch "/api/market/orderbook/") { throw "TradingView market integration is missing." }
    if ($heightFix -notmatch "frame\.style\.height") { throw "TradingView height fix v34 is missing." }
    if ($host -notmatch "no-store, no-cache, must-revalidate") { throw "Web2 no-cache host protection is missing." }
}

Clear-Host
Write-Host "SharipovAI - restore verified Web2 interface" -ForegroundColor Cyan
Write-Host "Baseline: $BaselineCommit" -ForegroundColor DarkCyan
Write-Host "Trading core, database and credentials will not be changed." -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path -LiteralPath $ProjectRoot)) { throw "Project folder not found: $ProjectRoot" }
$git = (Get-Command git.exe -ErrorAction Stop).Source
$gitDir = Join-Path $ProjectRoot ".git"
if (-not (Test-Path -LiteralPath $gitDir)) { throw "Not a Git repository: $ProjectRoot" }

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupRoot = Join-Path $ProjectRoot ("runtime\web2_restore_backup_" + $stamp)
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

$web2Path = Join-Path $ProjectRoot "dashboard\static\web2"
$hostPath = Join-Path $ProjectRoot "dashboard\web2_host.py"
if (Test-Path -LiteralPath $web2Path) {
    Copy-Item -LiteralPath $web2Path -Destination (Join-Path $backupRoot "web2") -Recurse -Force
}
if (Test-Path -LiteralPath $hostPath) {
    Copy-Item -LiteralPath $hostPath -Destination (Join-Path $backupRoot "web2_host.py") -Force
}

$branchBefore = (& $git -C $ProjectRoot branch --show-current).Trim()
$headBefore = (& $git -C $ProjectRoot rev-parse HEAD).Trim()
$statusBefore = & $git -C $ProjectRoot status --short
[IO.File]::WriteAllLines((Join-Path $backupRoot "git-status-before.txt"), [string[]]$statusBefore, [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText((Join-Path $backupRoot "git-state.txt"), "branch=$branchBefore`r`nhead=$headBefore`r`n", [Text.UTF8Encoding]::new($false))

Write-Host "Fetching verified UI history..." -ForegroundColor Cyan
& $git -C $ProjectRoot fetch origin --prune
if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }

& $git -C $ProjectRoot cat-file -e "$BaselineCommit`^{commit}"
if ($LASTEXITCODE -ne 0) { throw "Verified UI commit is unavailable after fetch: $BaselineCommit" }

Write-Host "Restoring Web2 files only..." -ForegroundColor Cyan
& $git -C $ProjectRoot restore --source=$BaselineCommit --worktree -- `
    dashboard/static/web2 `
    dashboard/web2_host.py
if ($LASTEXITCODE -ne 0) { throw "Git could not restore the verified Web2 files." }

$indexPath = Join-Path $web2Path "index.html"
$index = Get-Content -LiteralPath $indexPath -Raw
$cacheToken = "restore-$stamp"
$index = [Regex]::Replace($index, '\?v=[^"''\s>]+', "?v=$cacheToken")
[IO.File]::WriteAllText($indexPath, $index, [Text.UTF8Encoding]::new($false))

Assert-VerifiedWeb2Files -Root $ProjectRoot

Write-Host "Stopping stale UI process..." -ForegroundColor Cyan
Stop-SharipovAI -Root $ProjectRoot
Write-Host "Starting SharipovAI with restored Web2..." -ForegroundColor Cyan
Start-SharipovAI -Root $ProjectRoot

$envFile = Join-Path $ProjectRoot ".env.local"
$envValues = Read-EnvFile -Path $envFile
$username = [string]$envValues["ADMIN_USERNAME"]
$password = [string]$envValues["ADMIN_PASSWORD"]

if (-not [string]::IsNullOrWhiteSpace($username) -and -not [string]::IsNullOrWhiteSpace($password)) {
    try {
        $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/login" `
            -Method Post `
            -Body @{ username = $username; password = $password; next = "/" } `
            -WebSession $session `
            -UseBasicParsing `
            -MaximumRedirection 5 `
            -TimeoutSec 20
        if ($response.Content -notmatch "SharipovAI OS" -or $response.Content -notmatch "overview_runtime_v25\.js") {
            throw "Authenticated root did not return the restored Web2 shell."
        }
        Write-Host "Authenticated Web2 response verified." -ForegroundColor Green
    } catch {
        Write-Host "Warning: files and server are restored, but authenticated browser verification failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "WEB2_RESTORE_OK" -ForegroundColor Green
Write-Host "Verified UI baseline restored: $BaselineCommit" -ForegroundColor Green
Write-Host "Previous UI backup: $backupRoot" -ForegroundColor Cyan
Write-Host "Original branch/head preserved: $branchBefore / $headBefore" -ForegroundColor Cyan
Write-Host "Opening the correct SharipovAI OS root page..." -ForegroundColor Green

Start-Process "http://127.0.0.1:8000/"
Read-Host "Press Enter to close"
