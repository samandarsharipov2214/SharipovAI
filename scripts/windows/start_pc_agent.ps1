param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not $ProjectRoot) {
    $scriptDirectory = Split-Path -Parent $PSCommandPath
    $ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDirectory "..\.."))
}

Set-Location $ProjectRoot
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$agent = Join-Path $ProjectRoot "tools\pc_node_agent.py"
if (-not (Test-Path $python)) { throw "Python environment not found: $python" }
if (-not (Test-Path $agent)) { throw "PC agent not found: $agent" }

& $python $agent --project-root $ProjectRoot
exit $LASTEXITCODE
