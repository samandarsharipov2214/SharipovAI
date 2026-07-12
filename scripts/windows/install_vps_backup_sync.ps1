param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHost = $env:SHARIPOVAI_VPS_HOST,
    [string]$VpsUser = $(if ($env:SHARIPOVAI_VPS_USER) { $env:SHARIPOVAI_VPS_USER } else { "root" }),
    [string]$VpsAppDir = $(if ($env:SHARIPOVAI_VPS_APP_DIR) { $env:SHARIPOVAI_VPS_APP_DIR } else { "/opt/sharipovai-repo" }),
    [string]$IdentityFile = $env:SHARIPOVAI_VPS_IDENTITY_FILE,
    [int]$IntervalMinutes = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not $VpsHost) { throw "Set SHARIPOVAI_VPS_HOST or pass -VpsHost." }
if ($IntervalMinutes -lt 15) { throw "IntervalMinutes must be at least 15." }
$VpsAppDir = $VpsAppDir.TrimEnd('/')
if ($VpsAppDir -notmatch '^/[A-Za-z0-9._/-]+$' -or $VpsAppDir.Contains('/../') -or $VpsAppDir.Contains('//')) {
    throw "VPS app directory is invalid."
}
if ($IdentityFile) {
    if (-not (Test-Path $IdentityFile -PathType Leaf)) { throw "SSH identity file not found: $IdentityFile" }
    $IdentityFile = (Resolve-Path $IdentityFile).Path
}

$syncScript = Join-Path $ProjectRoot "scripts\windows\sync_vps_backup.ps1"
if (-not (Test-Path $syncScript)) { throw "Sync script not found: $syncScript" }

$taskName = "SharipovAI VPS Backup Sync"
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$syncScript`" -ProjectRoot `"$ProjectRoot`" -VpsHost `"$VpsHost`" -VpsUser `"$VpsUser`" -VpsAppDir `"$VpsAppDir`""
if ($IdentityFile) { $arguments += " -IdentityFile `"$IdentityFile`"" }
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

$syncArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $syncScript, "-ProjectRoot", $ProjectRoot, "-VpsHost", $VpsHost, "-VpsUser", $VpsUser, "-VpsAppDir", $VpsAppDir)
if ($IdentityFile) { $syncArgs += @("-IdentityFile", $IdentityFile) }
& $powershell @syncArgs
if ($LASTEXITCODE -ne 0) { throw "Initial VPS backup synchronization failed." }

$manifest = Join-Path $ProjectRoot "runtime\remote_backups\current\manifest.json"
if (-not (Test-Path $manifest)) { throw "Verified remote backup manifest was not created." }
Write-Host "Passive VPS backup synchronization installed and verified." -ForegroundColor Green
Write-Host "Scheduled task: $taskName"
