param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $ProjectRoot

function Import-LocalEnv([string]$Path) {
    if (-not (Test-Path $Path)) { throw "File not found: $Path. Run setup_pc.ps1 first." }
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) { continue }
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1], "Process")
    }
}

Import-LocalEnv (Join-Path $ProjectRoot ".env.local")
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Python virtual environment was not found. Run setup_pc.ps1 first." }

$hostAddress = if ($env:SHARIPOVAI_HOST) { $env:SHARIPOVAI_HOST } else { "127.0.0.1" }
$port = if ($env:SHARIPOVAI_PORT) { $env:SHARIPOVAI_PORT } else { "8000" }

& $python -m uvicorn dashboard:app --host $hostAddress --port $port
exit $LASTEXITCODE
