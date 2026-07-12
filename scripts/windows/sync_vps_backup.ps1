param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHost = $env:SHARIPOVAI_VPS_HOST,
    [string]$VpsUser = $(if ($env:SHARIPOVAI_VPS_USER) { $env:SHARIPOVAI_VPS_USER } else { "root" }),
    [string]$VpsAppDir = $(if ($env:SHARIPOVAI_VPS_APP_DIR) { $env:SHARIPOVAI_VPS_APP_DIR } else { "/opt/sharipovai" })
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot
$runtime = Join-Path $ProjectRoot "runtime"
$statusPath = Join-Path $runtime "vps_backup_sync_status.json"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$startedAt = [DateTimeOffset]::UtcNow
$lockStream = $null
$lockPath = Join-Path $runtime "vps_backup_sync.lock"
$stageRoot = $null

function Save-SyncStatus([string]$Status, [string]$Message, [string]$ManifestCreatedAt = "", [int]$FileCount = 0) {
    [ordered]@{
        schema = 1
        status = $Status
        message = $Message
        started_at = $startedAt.ToString("o")
        completed_at = [DateTimeOffset]::UtcNow.ToString("o")
        vps_host = $VpsHost
        manifest_created_at = $ManifestCreatedAt
        file_count = $FileCount
    } | ConvertTo-Json | Set-Content -Path $statusPath -Encoding UTF8
}

try {
    if (-not $VpsHost) { throw "Set SHARIPOVAI_VPS_HOST or pass -VpsHost." }
    if ($VpsHost -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') { throw "VPS host is invalid." }
    if ($VpsUser -notmatch '^[A-Za-z_][A-Za-z0-9_-]{0,31}$') { throw "VPS user is invalid." }
    $VpsAppDir = $VpsAppDir.TrimEnd('/')
    if ($VpsAppDir -notmatch '^/[A-Za-z0-9._/-]+$' -or $VpsAppDir.Contains('/../') -or $VpsAppDir.Contains('//')) {
        throw "VPS app directory is invalid."
    }

    $python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $python -PathType Leaf)) { throw "Python environment not found. Run setup_pc.ps1 first." }
    $verifier = Join-Path $ProjectRoot "tools\verify_backup_archive.py"
    if (-not (Test-Path $verifier -PathType Leaf)) { throw "Backup verifier is missing." }
    $ssh = Get-Command ssh -ErrorAction Stop
    $scp = Get-Command scp -ErrorAction Stop

    try {
        $lockStream = [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    } catch {
        throw "Another VPS backup synchronization is already running."
    }

    $root = Join-Path $runtime "remote_backups"
    $stageRoot = Join-Path $root (".staging-$PID-" + [Guid]::NewGuid().ToString("N"))
    $downloads = Join-Path $stageRoot "downloads"
    $snapshotStage = Join-Path $stageRoot "snapshot"
    $current = Join-Path $root "current"
    $previous = Join-Path $root "previous"
    New-Item -ItemType Directory -Force -Path $downloads | Out-Null

    $target = "$VpsUser@$VpsHost"
    $remoteCommand = "APP_DIR='$VpsAppDir' bash '$VpsAppDir/deploy/vps/export_backup.sh'"
    $remoteArchive = (& $ssh.Source $target $remoteCommand | Select-Object -Last 1).Trim()
    if ($LASTEXITCODE -ne 0) { throw "VPS backup export failed." }
    $expectedPrefix = "$VpsAppDir/deploy/vps/backups/sharipovai-"
    if (-not $remoteArchive.StartsWith($expectedPrefix, [System.StringComparison]::Ordinal) -or
        $remoteArchive -notmatch '^/[A-Za-z0-9._/-]+/sharipovai-[0-9]{8}T[0-9]{6}Z\.tar\.gz$') {
        throw "VPS returned an unsafe backup path."
    }

    $archiveName = Split-Path $remoteArchive -Leaf
    $localArchive = Join-Path $downloads $archiveName
    & $scp.Source "$target`:$remoteArchive" $localArchive
    if ($LASTEXITCODE -ne 0) { throw "Archive download failed." }
    & $scp.Source "$target`:$remoteArchive.sha256" "$localArchive.sha256"
    if ($LASTEXITCODE -ne 0) { throw "Checksum download failed." }

    $expected = ((Get-Content "$localArchive.sha256" -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$') { throw "Downloaded checksum file is invalid." }
    $actual = (Get-FileHash -Algorithm SHA256 $localArchive).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "Downloaded backup checksum mismatch." }

    & $python -m tools.verify_backup_archive --archive $localArchive --destination $snapshotStage
    if ($LASTEXITCODE -ne 0) { throw "Backup archive integrity verification failed." }
    $manifest = Join-Path $snapshotStage "manifest.json"
    if (-not (Test-Path $manifest -PathType Leaf)) { throw "Verified backup manifest is missing." }
    $payload = Get-Content $manifest -Raw | ConvertFrom-Json

    Remove-Item $previous -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $current) { Move-Item $current $previous }
    try {
        Move-Item $snapshotStage $current
    } catch {
        Remove-Item $current -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path $previous) { Move-Item $previous $current }
        throw
    }

    Save-SyncStatus "ok" "Verified VPS backup synchronized." ([string]$payload.created_at) ([int]$payload.file_count)
    Write-Host "Verified VPS backup synchronized: $current" -ForegroundColor Green
} catch {
    Save-SyncStatus "error" $_.Exception.Message
    throw
} finally {
    if ($stageRoot) { Remove-Item $stageRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if ($lockStream) { $lockStream.Dispose() }
    Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
}
