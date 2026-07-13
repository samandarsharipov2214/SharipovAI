param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "04:00",
    [int]$RetainRuns = 12
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

if ($RetainRuns -lt 2 -or $RetainRuns -gt 52) {
    throw "RetainRuns must be between 2 and 52."
}
try {
    $scheduledDay = [System.DayOfWeek][System.Enum]::Parse([System.DayOfWeek], $DayOfWeek, $true)
} catch {
    throw "DayOfWeek is invalid."
}
$parsedTime = [DateTime]::MinValue
if (-not [DateTime]::TryParseExact($Time, "HH:mm", [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$parsedTime)) {
    throw "Time must use HH:mm format."
}

$drillScript = Join-Path $ProjectRoot "scripts\windows\test_isolated_restore.ps1"
if (-not (Test-Path $drillScript -PathType Leaf)) {
    throw "Restore drill script not found: $drillScript"
}
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python -PathType Leaf)) {
    throw "Python environment not found. Run setup_pc.ps1 first."
}

$taskName = "SharipovAI Weekly Restore Drill"
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$drillScript`" -ProjectRoot `"$ProjectRoot`" -RetainRuns $RetainRuns"
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $ProjectRoot
$triggerAt = (Get-Date).Date.Add($parsedTime.TimeOfDay)
$trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $scheduledDay -At $triggerAt
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

& $powershell -NoProfile -ExecutionPolicy Bypass -File $drillScript -ProjectRoot $ProjectRoot -RetainRuns $RetainRuns
if ($LASTEXITCODE -ne 0) {
    throw "Initial weekly restore drill verification failed."
}

$statusPath = Join-Path $ProjectRoot "runtime\restore_drill_status.json"
if (-not (Test-Path $statusPath -PathType Leaf)) {
    throw "Restore drill status file was not created."
}
$status = Get-Content $statusPath -Raw | ConvertFrom-Json
if ($status.status -ne "ok" -or $status.activation_performed -ne $false -or $status.network_services_started -ne $false) {
    throw "Restore drill status verification failed."
}

Write-Host "Weekly passive restore drill installed and verified." -ForegroundColor Green
Write-Host "Scheduled task: $taskName"
Write-Host "Schedule: $scheduledDay at $Time (Windows local time; starts when available if missed)."
Write-Host "Restore drills: $(Join-Path $ProjectRoot 'runtime\restore_drills')"
Write-Host "Latest status: $statusPath"
Write-Host "Retention: last $RetainRuns restore drills"
