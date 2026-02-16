[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\bootstrap.ps1 first."
}

Set-Location $projectRoot

# Lint and type-check are split so it is obvious which stage failed.
Write-Host "[run-quality] Running ruff check"
& $venvPython -m ruff check src tests

Write-Host "[run-quality] Running mypy"
& $venvPython -m mypy src
