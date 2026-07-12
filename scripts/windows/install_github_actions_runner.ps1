[CmdletBinding()]
param(
    [string]$Repository = $(if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { 'samandarsharipov2214/SharipovAI' }),
    [string]$RunnerRoot = 'C:\SharipovAI-ActionsRunner',
    [string]$RunnerName = "sharipovai-pc-$env:COMPUTERNAME",
    [string]$Labels = 'sharipovai-windows-ci',
    [string]$RegistrationToken = $env:GITHUB_RUNNER_TOKEN,
    [string]$GitHubToken = $env:GH_TOKEN
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run PowerShell as Administrator.'
    }
}

function Invoke-GitHubApi {
    param(
        [Parameter(Mandatory)] [ValidateSet('GET', 'POST', 'PATCH')] [string]$Method,
        [Parameter(Mandatory)] [string]$Uri,
        [object]$Body
    )
    if (-not $GitHubToken) { throw 'GH_TOKEN is required for this API call.' }
    $headers = @{
        Authorization = "Bearer $GitHubToken"
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
    }
    $params = @{ Method = $Method; Uri = $Uri; Headers = $headers }
    if ($null -ne $Body) {
        $params.ContentType = 'application/json'
        $params.Body = ($Body | ConvertTo-Json -Compress)
    }
    Invoke-RestMethod @params
}

Assert-Administrator
if ($Repository -notmatch '^[^/]+/[^/]+$') { throw 'Repository must be owner/repo.' }

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$release = Invoke-RestMethod -Uri 'https://api.github.com/repos/actions/runner/releases/latest' -Headers @{ Accept = 'application/vnd.github+json' }
$tag = [string]$release.tag_name
if (-not $tag) { throw 'Unable to determine the latest actions/runner release.' }
$version = $tag.TrimStart('v')
$archiveName = "actions-runner-win-x64-$version.zip"
$downloadUrl = "https://github.com/actions/runner/releases/download/$tag/$archiveName"

New-Item -ItemType Directory -Path $RunnerRoot -Force | Out-Null
$configPath = Join-Path $RunnerRoot 'config.cmd'
if (-not (Test-Path $configPath)) {
    $archivePath = Join-Path $env:TEMP $archiveName
    Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath -UseBasicParsing
    Expand-Archive -Path $archivePath -DestinationPath $RunnerRoot -Force
    Remove-Item $archivePath -Force -ErrorAction SilentlyContinue
}

if (-not $RegistrationToken -and $GitHubToken) {
    $tokenResponse = Invoke-GitHubApi -Method POST -Uri "https://api.github.com/repos/$Repository/actions/runners/registration-token"
    $RegistrationToken = [string]$tokenResponse.token
}
if (-not $RegistrationToken) {
    throw 'Set GH_TOKEN (repo admin) or one-time GITHUB_RUNNER_TOKEN.'
}

Push-Location $RunnerRoot
try {
    if (Test-Path (Join-Path $RunnerRoot '.runner')) {
        & .\svc.cmd stop | Out-Null
        & .\svc.cmd uninstall | Out-Null
        $removeToken = $env:GITHUB_RUNNER_REMOVE_TOKEN
        if (-not $removeToken -and $GitHubToken) {
            $removeResponse = Invoke-GitHubApi -Method POST -Uri "https://api.github.com/repos/$Repository/actions/runners/remove-token"
            $removeToken = [string]$removeResponse.token
        }
        if ($removeToken) {
            & .\config.cmd remove --unattended --token $removeToken | Out-Null
        }
    }

    & .\config.cmd `
        --url "https://github.com/$Repository" `
        --token $RegistrationToken `
        --name $RunnerName `
        --labels $Labels `
        --work '_work' `
        --unattended `
        --replace `
        --runasservice
    if ($LASTEXITCODE -ne 0) { throw "Runner configuration failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

if ($GitHubToken) {
    $variableName = 'SHARIPOVAI_WINDOWS_SELF_HOSTED_CI'
    $body = @{ name = $variableName; value = '1' }
    try {
        Invoke-GitHubApi -Method PATCH -Uri "https://api.github.com/repos/$Repository/actions/variables/$variableName" -Body $body | Out-Null
    } catch {
        Invoke-GitHubApi -Method POST -Uri "https://api.github.com/repos/$Repository/actions/variables" -Body $body | Out-Null
    }
} else {
    Write-Warning 'Runner installed. Set repository variable SHARIPOVAI_WINDOWS_SELF_HOSTED_CI=1 to enable the workflow.'
}

Write-Host "GitHub Actions runner '$RunnerName' installed with label '$Labels'."
