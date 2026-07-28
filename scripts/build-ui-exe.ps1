[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "scripts\ui_entrypoint.py"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\bootstrap.ps1 first."
}

if (-not (Test-Path $entrypoint)) {
    throw "UI entrypoint not found at scripts\ui_entrypoint.py."
}

Set-Location $projectRoot

# Build from the package-aware entrypoint so relative imports resolve correctly.
& $venvPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "pip install pyinstaller failed with exit code $LASTEXITCODE"
}

& $venvPython -m PyInstaller `
    --noconfirm `
    --onefile `
    --windowed `
    --name mc-ui `
    --paths .\src `
    --collect-data customtkinter `
    .\scripts\ui_entrypoint.py
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host "Built EXE: $projectRoot\dist\mc-ui.exe"
