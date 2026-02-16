[CmdletBinding()]
param(
    # Quick smoke target for fetch + parse validation.
    [Parameter(Mandatory = $false)]
    [string]$Url = "https://example.com",
    # Optional output file path for smoke payload capture.
    [Parameter(Mandatory = $false)]
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\bootstrap.ps1 first."
}

Set-Location $projectRoot

$args = @("-m", "mc_ws_dl_t", $Url, "--log-level", "INFO")
if ($OutputPath) {
    $args += @("--output", $OutputPath)
}

Write-Host "[run-smoke] Running downloader smoke test against: $Url"
& $venvPython @args
