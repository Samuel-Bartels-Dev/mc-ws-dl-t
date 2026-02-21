[CmdletBinding()]
param(
    # Optional single adapter name (example: mangatown).
    [Parameter(Mandatory = $false)]
    [string]$Site = "",
    # Maximum runtime budget per site in seconds.
    [Parameter(Mandatory = $false)]
    [int]$MaxSecondsPerSite = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\bootstrap.ps1 first."
}

Set-Location $projectRoot

$args = @(
    ".\scripts\smoke_test_sites.py",
    "--max-seconds-per-site", "$MaxSecondsPerSite"
)
if ($Site) {
    $args += @("--site", $Site)
}

Write-Host "[run-smoke] Running parser smoke tests for all supported sites."
& $venvPython @args
