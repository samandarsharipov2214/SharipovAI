param(
    [string]$Username = "Samandar2212"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot ".env"

Write-Host "SharipovAI local auth setup" -ForegroundColor Cyan
Write-Host "This script creates a local .env file. It is not uploaded to GitHub." -ForegroundColor DarkGray
Write-Host ""

if (Test-Path $envPath) {
    $answer = Read-Host ".env already exists. Overwrite it? Type YES"
    if ($answer -ne "YES") {
        Write-Host "Cancelled. Existing .env was not changed." -ForegroundColor Yellow
        exit 0
    }
}

if (-not $Username -or $Username.Trim().Length -lt 3) {
    $Username = Read-Host "Admin username"
}

$securePassword = Read-Host "Admin password" -AsSecureString
$plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword))

if (-not $plainPassword -or $plainPassword.Length -lt 6) {
    Write-Host "Password must be at least 6 characters." -ForegroundColor Red
    exit 1
}

$secretBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
$secret = [Convert]::ToHexString($secretBytes).ToLower()

$content = @"
ADMIN_USERNAME=$Username
ADMIN_PASSWORD=$plainPassword
AUTH_SECRET=$secret
AUTH_ALLOW_REGISTRATION=1
AUTH_USERS_FILE=data/dashboard_users.json
AUTH_ACCESS_REQUESTS_FILE=data/access_requests.json
AUTH_SECURITY_EVENTS_FILE=data/security_events.json
"@

Set-Content -Path $envPath -Value $content -Encoding UTF8

Write-Host ""
Write-Host ".env created successfully." -ForegroundColor Green
Write-Host "Username: $Username" -ForegroundColor Green
Write-Host "Next command:" -ForegroundColor Cyan
Write-Host "python -m uvicorn dashboard.app:app --reload" -ForegroundColor White
Write-Host ""
Write-Host "Open: http://127.0.0.1:8000/login" -ForegroundColor Cyan
