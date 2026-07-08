# Creates a local .env file for SharipovAI login.
# The .env file is local only and must not be committed to GitHub.

$ErrorActionPreference = "Stop"

Write-Host "SharipovAI local auth setup" -ForegroundColor Cyan
Write-Host "This will create .env in the current project folder." -ForegroundColor Gray

$username = Read-Host "Admin username" 
if ([string]::IsNullOrWhiteSpace($username)) {
    $username = "Samandar2212"
}

$securePassword = Read-Host "Admin password" -AsSecureString
$passwordPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPtr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPtr)
}

if ([string]::IsNullOrWhiteSpace($password)) {
    Write-Host "Password is empty. .env was not created." -ForegroundColor Red
    exit 1
}

$secretBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
$authSecret = [Convert]::ToHexString($secretBytes).ToLower()

$envContent = @"
ADMIN_USERNAME=$username
ADMIN_PASSWORD=$password
AUTH_SECRET=$authSecret
AUTH_ALLOW_REGISTRATION=1
AUTH_USERS_FILE=data/dashboard_users.json
AUTH_ACCESS_REQUESTS_FILE=data/access_requests.json
AUTH_SECURITY_EVENTS_FILE=data/security_events.json
"@

Set-Content -Path ".env" -Value $envContent -Encoding UTF8

Write-Host ".env created successfully." -ForegroundColor Green
Write-Host "Now run:" -ForegroundColor Cyan
Write-Host "python -m uvicorn dashboard.app:app --reload" -ForegroundColor Yellow
