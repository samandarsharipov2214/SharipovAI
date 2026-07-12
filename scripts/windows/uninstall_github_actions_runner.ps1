[CmdletBinding()]
param(
    [string]$Repository = $(if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { 'samandarsharipov2214/SharipovAI' }),
    [string]$RunnerRoot = 'C:\SharipovAI-ActionsRunner',
    [string]$GitHubToken = $env:GH_TOKEN
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run PowerShell as Administrator.'
}

if (Test-Path (Join-Path $RunnerRoot 'svc.cmd')) {
    Push-Location $RunnerRoot
    try {
        & .\svc.cmd stop | Out-Null
        & .\svc.cmd uninstall | Out-Null
        $removeToken = $env:GITHUB_RUNNER_REMOVE_TOKEN
        if (-not $removeToken -and $GitHubToken) {
            $headers = @{
                Authorization = "Bearer $GitHubToken"
                Accept = 'application/vnd.github+json'
                'X-GitHub-Api-Version' = '2022-11-28'
            }
            $response = Invoke-RestMethod -Method POST -Uri "https://api.github.com/repos/$Repository/actions/runners/remove-token" -Headers $headers
            $removeToken = [string]$response.token
        }
        if ($removeToken -and (Test-Path (Join-Path $RunnerRoot '.runner'))) {
            & .\config.cmd remove --unattended --token $removeToken | Out-Null
        }
    } finally {
        Pop-Location
    }
}

if ($GitHubToken) {
    $headers = @{
        Authorization = "Bearer $GitHubToken"
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    $body = @{ name = 'SHARIPOVAI_WINDOWS_SELF_HOSTED_CI'; value = '0' } | ConvertTo-Json -Compress
    try {
        Invoke-RestMethod -Method PATCH -Uri "https://api.github.com/repos/$Repository/actions/variables/SHARIPOVAI_WINDOWS_SELF_HOSTED_CI" -Headers $headers -ContentType 'application/json' -Body $body | Out-Null
    } catch {
        Write-Warning $_.Exception.Message
    }
}

Remove-Item -Path $RunnerRoot -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'GitHub Actions Windows runner removed.'
