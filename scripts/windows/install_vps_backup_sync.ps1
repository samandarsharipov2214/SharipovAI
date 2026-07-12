param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHost = $env:SHARIPOVAI_VPS_HOST,
    [string]$VpsUser = $(if ($env:SHARIPOVAI_VPS_USER) { $env:SHARIPOVAI_VPS_USER } else { "root" }),
    [int]$IntervalMinutes = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not $VpsHost) { throw "Set SHARIPOVAI_VPS_HOST or pass -VpsHost." }
if ($IntervalMinutes -lt 15) { throw "IntervalMinutes must be at least 15." }

$syncScript = Join-Path $ProjectRoot "scripts\windows\sync_vps_backup.ps1"
if (-not (Test-Path $syncScript)) { throw "Sync script not found: $syncScript" }

$taskName = "SharipovAI VPS Backup Sync"
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$syncScript`" -ProjectRoot `"$ProjectRoot`" -VpsHost `"$VpsHost`" -VpsUser `"$VpsUser`""
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

& $powershell -NoProfile -ExecutionPolicy Bypass -File $syncScript -ProjectRoot $ProjectRoot -VpsHost $VpsHost -VpsUser $VpsUser
if ($LASTEXITCODE -ne 0) { throw "Initial VPS backup synchronization failed." }

$manifest = Join-Path $ProjectRoot "runtime\remote_backups\current\manifest.json"
if (-not (Test-Path $manifest)) { throw "Verified remote backup manifest was not created." }
Write-Host "Passive VPS backup synchronization installed and verified." -ForegroundColor Green
Write-Host "Scheduled task: $taskName"
