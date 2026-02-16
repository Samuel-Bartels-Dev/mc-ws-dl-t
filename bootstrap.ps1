[CmdletBinding()]
param(
    # Include selenium dependencies when you need JS-rendered page support.
    [switch]$InstallDynamic
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    # Consistent prefix keeps bootstrap output easy to scan in terminal logs.
    Write-Host "[bootstrap] $Message"
}

# Script always runs relative to project root so path handling is predictable.
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $projectRoot

# Support both python and py launcher since workstation setups vary.
$pythonLauncher = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonLauncher = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonLauncher = "py"
} else {
    throw "Python was not found on PATH. Install Python 3.10+ first."
}

function Invoke-SystemPython {
    param([string[]]$Args)

    # Use whichever launcher exists so we can bootstrap on more machines.
    if ($pythonLauncher -eq "python") {
        & python @Args
    } else {
        & py -3 @Args
    }
}

$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    # Only create virtual environment if not present.
    Write-Step "Creating virtual environment at .venv"
    Invoke-SystemPython -Args @("-m", "venv", $venvPath)
}

# Check common interpreter locations to keep this portable.
$venvPythonCandidates = @(
    (Join-Path $venvPath "Scripts\python.exe"),
    (Join-Path $venvPath "Scripts\python"),
    (Join-Path $venvPath "bin\python")
)
$venvPython = $venvPythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $venvPython) {
    throw "Virtual environment was not created correctly. No python interpreter found under '$venvPath'."
}

Write-Step "Upgrading pip in .venv"
& $venvPython -m pip install --upgrade pip

# Default install is dev tooling; dynamic adds selenium extras.
$extras = if ($InstallDynamic) { ".[dev,dynamic]" } else { ".[dev]" }
Write-Step "Installing package with extras $extras"
& $venvPython -m pip install -e $extras

$vscodeDir = Join-Path $projectRoot ".vscode"
if (-not (Test-Path $vscodeDir)) {
    New-Item -Path $vscodeDir -ItemType Directory -Force | Out-Null
}

$settingsPath = Join-Path $vscodeDir "settings.json"
# Keep VS Code pointed at the project venv to avoid global interpreter drift.
$settingsJson = @'
{
  "python.defaultInterpreterPath": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": [
    "tests"
  ]
}
'@

Set-Content -Path $settingsPath -Value $settingsJson -Encoding UTF8

Write-Step "Bootstrap complete."
Write-Step "Interpreter: .venv\\Scripts\\python.exe"
Write-Step "Run tests: .\\.venv\\Scripts\\python.exe -m pytest"
