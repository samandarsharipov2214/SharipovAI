param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHost = $env:SHARIPOVAI_VPS_HOST,
    [string]$VpsUser = $(if ($env:SHARIPOVAI_VPS_USER) { $env:SHARIPOVAI_VPS_USER } else { "root" }),
    [string]$VpsAppDir = $(if ($env:SHARIPOVAI_VPS_APP_DIR) { $env:SHARIPOVAI_VPS_APP_DIR } else { "/opt/sharipovai" })
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not $VpsHost) { throw "Set SHARIPOVAI_VPS_HOST or pass -VpsHost." }

$ssh = Get-Command ssh -ErrorAction Stop
$scp = Get-Command scp -ErrorAction Stop
$root = Join-Path $ProjectRoot "runtime\remote_backups"
$stage = Join-Path $root ".staging"
$current = Join-Path $root "current"
$previous = Join-Path $root "previous"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$target = "$VpsUser@$VpsHost"
$remoteCommand = "APP_DIR='$VpsAppDir' bash '$VpsAppDir/deploy/vps/export_backup.sh'"
$remoteArchive = (& $ssh.Source $target $remoteCommand | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or -not $remoteArchive.EndsWith(".tar.gz")) {
    throw "VPS backup export failed."
}

$archiveName = Split-Path $remoteArchive -Leaf
$localArchive = Join-Path $stage $archiveName
& $scp.Source "$target`:$remoteArchive" $localArchive
if ($LASTEXITCODE -ne 0) { throw "Archive download failed." }
& $scp.Source "$target`:$remoteArchive.sha256" "$localArchive.sha256"
if ($LASTEXITCODE -ne 0) { throw "Checksum download failed." }

$expected = ((Get-Content "$localArchive.sha256" -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
$actual = (Get-FileHash -Algorithm SHA256 $localArchive).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "Downloaded backup checksum mismatch." }

tar -xzf $localArchive -C $stage
if ($LASTEXITCODE -ne 0) { throw "Backup extraction failed." }
$manifest = Join-Path $stage "manifest.json"
$data = Join-Path $stage "data"
if (-not (Test-Path $manifest) -or -not (Test-Path $data)) { throw "Backup payload is incomplete." }

$payload = Get-Content $manifest -Raw | ConvertFrom-Json
foreach ($entry in $payload.files) {
    $path = Join-Path $data ($entry.path -replace "/", "\")
    if (-not (Test-Path $path)) { throw "Backup file missing: $($entry.path)" }
    $hash = (Get-FileHash -Algorithm SHA256 $path).Hash.ToLowerInvariant()
    if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "Backup file checksum mismatch: $($entry.path)" }
}

Remove-Item $previous -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $current) { Move-Item $current $previous }
Move-Item $stage $current
Write-Host "Verified VPS backup synchronized: $current" -ForegroundColor Green
