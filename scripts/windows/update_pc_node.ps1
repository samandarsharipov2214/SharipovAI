param(
    [string]$Archive = "",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-ProjectRoot {
    param([string]$RequestedRoot)

    if ($RequestedRoot -and (Test-Path $RequestedRoot)) {
        return (Resolve-Path $RequestedRoot).Path
    }

    $scriptPath = $MyInvocation.ScriptName
    if (-not $scriptPath) {
        $scriptPath = $PSCommandPath
    }
    if ($scriptPath) {
        $candidate = [System.IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $scriptPath) "..\.."))
        if (Test-Path (Join-Path $candidate "requirements.txt")) {
            return $candidate
        }
    }

    $knownRoots = @(
        "D:\SharipovAI_Server\SharipovAI",
        (Join-Path $env:USERPROFILE "SharipovAI"),
        (Join-Path $env:USERPROFILE "Desktop\SharipovAI")
    )
    foreach ($candidate in $knownRoots) {
        if ($candidate -and (Test-Path (Join-Path $candidate "requirements.txt"))) {
            return (Resolve-Path $candidate).Path
        }
    }

    throw "SharipovAI project folder was not found."
}

function Resolve-UpdateArchive {
    param([string]$RequestedArchive)

    if ($RequestedArchive) {
        if (-not (Test-Path $RequestedArchive -PathType Leaf)) {
            throw "Update ZIP was not found: $RequestedArchive"
        }
        return (Resolve-Path $RequestedArchive).Path
    }

    $searchFolders = @(
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "OneDrive\Downloads"),
        (Join-Path $env:USERPROFILE "OneDrive\Desktop"),
        "D:\Downloads",
        "D:\Загрузки"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $archive = Get-ChildItem -Path $searchFolders -Filter "SharipovAI*.zip" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike "*Updater_Bootstrap*" -and $_.Name -notlike "*Windows_Paper_Fix*" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if (-not $archive) {
        throw "No SharipovAI update ZIP was found in Downloads or Desktop."
    }
    return $archive.FullName
}

$ProjectRoot = Resolve-ProjectRoot -RequestedRoot $ProjectRoot
$archivePath = Resolve-UpdateArchive -RequestedArchive $Archive
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$updater = Join-Path $ProjectRoot "tools\pc_node_update.py"
$agentScript = Join-Path $ProjectRoot "scripts\windows\start_pc_agent.ps1"
$checkScript = Join-Path $ProjectRoot "scripts\windows\check_pc_node.ps1"

if (-not (Test-Path $python)) { throw "Python environment not found: $python" }
if (-not (Test-Path $updater)) { throw "Updater not found: $updater" }
if (-not (Test-Path $agentScript)) { throw "PC Agent launcher not found: $agentScript" }
if (-not (Test-Path $checkScript)) { throw "Health-check script not found: $checkScript" }

Write-Host "Project: $ProjectRoot"
Write-Host "Update ZIP: $archivePath"
Write-Host "Stopping SharipovAI managed processes..."
Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and
        ($_.CommandLine -like "*$ProjectRoot*") -and
        (($_.CommandLine -like "*pc_node_agent.py*") -or ($_.CommandLine -like "*uvicorn*") -or ($_.CommandLine -like "*pc_node_backup.py*"))
    } |
    ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch { }
    }

$pidDir = Join-Path $ProjectRoot "runtime\pids"
Remove-Item (Join-Path $pidDir "pc_agent.pid") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $pidDir "pc_node.pid") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $pidDir "backup.pid") -Force -ErrorAction SilentlyContinue

& $python $updater --archive $archivePath --project-root $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "SharipovAI update failed. Previous code was restored automatically."
}

$utf8Bom = New-Object System.Text.UTF8Encoding($true)
Get-ChildItem (Join-Path $ProjectRoot "scripts\windows\*.ps1") -File | ForEach-Object {
    $text = [System.IO.File]::ReadAllText($_.FullName, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($_.FullName, $text, $utf8Bom)
}

Write-Host "Starting unified SharipovAI PC Agent..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $agentScript -ProjectRoot $ProjectRoot
if ($LASTEXITCODE -ne 0) {
    throw "Update was installed, but PC Agent did not start successfully."
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checkScript -ProjectRoot $ProjectRoot -RequireManagedProcesses
if ($LASTEXITCODE -ne 0) {
    throw "Update was installed, but the final PC node health check failed."
}

Write-Host "SharipovAI update and verification completed." -ForegroundColor Green
