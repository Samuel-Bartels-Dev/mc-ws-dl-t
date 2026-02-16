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

# Launches the desktop UI against the project environment.
& $venvPython -m mc_ws_dl_t.ui
