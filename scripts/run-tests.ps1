[CmdletBinding()]
param(
    # Pass through extra pytest args when needed (example: -PytestArgs "-k parser -q").
    [string]$PytestArgs = "-q"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\bootstrap.ps1 first."
}

# Run tests from project root so pytest uses local config/testpaths.
Set-Location $projectRoot
Write-Host "[run-tests] Running pytest $PytestArgs"

$argList = @("-m", "pytest")
if ($PytestArgs) {
    # Keep arg handling simple and readable for common flag strings.
    $argList += ($PytestArgs -split "\s+" | Where-Object { $_ })
}

& $venvPython @argList
