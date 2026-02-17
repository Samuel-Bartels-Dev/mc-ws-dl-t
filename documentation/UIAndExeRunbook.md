# UI and EXE Runbook

This runbook covers:
- launching the desktop UI
- building package artifacts (`dist/`)
- building a standalone Windows `.exe`

## Prerequisites

- PowerShell
- Python 3.10+
- Project bootstrap completed

From project root:

```powershell
.\bootstrap.ps1
```

## Start the UI

Recommended:

```powershell
.\scripts\run-ui.ps1
```

Direct entrypoint (same environment):

```powershell
.\.venv\Scripts\mc-ui.exe
```

## Build Package Artifacts (Wheel + Source)

```powershell
.\.venv\Scripts\python.exe -m pip install build
.\.venv\Scripts\python.exe -m build
```

Output:
- `dist\*.whl`
- `dist\*.tar.gz`

## Build Standalone Windows EXE (PyInstaller)

Recommended (uses the safe package entrypoint):

```powershell
.\scripts\build-ui-exe.ps1
```

Manual build:

Install PyInstaller in the project venv:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
```

Build one-file windowed executable:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name mc-ui --paths .\src .\scripts\ui_entrypoint.py
```

Output:
- `dist\mc-ui.exe`

Important:
- do not build from `src\mc_ws_dl_t\ui.py` directly
- building from `ui.py` can fail with `ImportError: attempted relative import with no known parent package`

## Quick Verification

After build:

```powershell
.\dist\mc-ui.exe
```

If UI does not launch:
- rerun bootstrap (`.\bootstrap.ps1`)
- rebuild with PyInstaller command above
- check project root for dependency/import errors
