param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$VpsHost = "85.137.88.17",
    [string]$VpsUser = "root",
    [string]$VpsAppDir = "/opt/sharipovai-repo",
    [int]$IntervalMinutes = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

if ($VpsHost -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$') { throw "VPS host is invalid." }
if ($VpsUser -notmatch '^[A-Za-z_][A-Za-z0-9_-]{0,31}$') { throw "VPS user is invalid." }
if ($IntervalMinutes -lt 15) { throw "IntervalMinutes must be at least 15." }
$VpsAppDir = $VpsAppDir.TrimEnd('/')
if ($VpsAppDir -notmatch '^/[A-Za-z0-9._/-]+$' -or $VpsAppDir.Contains('/../') -or $VpsAppDir.Contains('//')) {
    throw "VPS app directory is invalid."
}

$ssh = Get-Command ssh.exe -ErrorAction Stop
$keygen = Get-Command ssh-keygen.exe -ErrorAction Stop
$sshDir = Join-Path $env:USERPROFILE ".ssh"
$keyPath = Join-Path $sshDir "sharipovai_backup_ed25519"
$publicKeyPath = "$keyPath.pub"
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

if (-not (Test-Path $keyPath -PathType Leaf)) {
    @("", "") | & $keygen.Source -q -t ed25519 -f $keyPath -C "sharipovai-backup@$env:COMPUTERNAME"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $keyPath -PathType Leaf)) {
        throw "Failed to create the dedicated SharipovAI backup SSH key."
    }
}

$publicKeyOutput = & $keygen.Source -y -f $keyPath
$keygenExitCode = $LASTEXITCODE
$publicKey = if ($null -eq $publicKeyOutput) { "" } else { ((@($publicKeyOutput) -join "").Trim()) }
if ($keygenExitCode -ne 0 -or $publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+(?: .+)?$') {
    throw "Failed to derive a valid SSH public key from the private key."
}
$publicKey | Set-Content -Path $publicKeyPath -Encoding Ascii

$target = "$VpsUser@$VpsHost"
$keyPayload = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($publicKey))
$remoteInstall = "set -eu; umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys; key=`$(printf '%s' '$keyPayload' | base64 -d); grep -qxF `"`$key`" ~/.ssh/authorized_keys || printf '%s\n' `"`$key`" >> ~/.ssh/authorized_keys"
& $ssh.Source $target $remoteInstall
if ($LASTEXITCODE -ne 0) { throw "Failed to install the backup SSH key on the VPS." }

$probeOutput = & $ssh.Source -i $keyPath -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=15 $target "printf backup-key-ok"
$probeExitCode = $LASTEXITCODE
$probe = if ($null -eq $probeOutput) { "" } else { ([string]$probeOutput).Trim() }
if ($probeExitCode -ne 0 -or $probe -ne "backup-key-ok") {
    throw "Passwordless VPS authentication check failed."
}

$installer = Join-Path $ProjectRoot "scripts\windows\install_vps_backup_sync.ps1"
if (-not (Test-Path $installer -PathType Leaf)) { throw "Backup synchronization installer is missing." }
$powershell = (Get-Command powershell.exe -ErrorAction Stop).Source
& $powershell -NoProfile -ExecutionPolicy Bypass -File $installer -ProjectRoot $ProjectRoot -VpsHost $VpsHost -VpsUser $VpsUser -VpsAppDir $VpsAppDir -IdentityFile $keyPath -IntervalMinutes $IntervalMinutes
if ($LASTEXITCODE -ne 0) { throw "Backup synchronization task installation failed." }

Write-Host "SharipovAI passive backup automation is installed and verified." -ForegroundColor Green
Write-Host "SSH key: $keyPath"
Write-Host "Schedule: every $IntervalMinutes minutes while this Windows user is signed in."
