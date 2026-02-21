# Build Windows EXE

This project builds a standalone UI executable with PyInstaller.

## Prerequisites
- Windows
- Python 3.10+
- Project virtual environment created with `bootstrap.ps1`

From repo root:

```powershell
.\bootstrap.ps1
```

## Build Command

```powershell
.\scripts\build-ui-exe.ps1
```

Build script behavior:
- installs PyInstaller in the project `.venv` if needed
- builds from `scripts/ui_entrypoint.py` (package-safe entrypoint)
- writes executable to `dist/mc-ui.exe`

## Manual Build (Equivalent)

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --name mc-ui --paths .\src .\scripts\ui_entrypoint.py
```

## Verify EXE

```powershell
.\dist\mc-ui.exe
```

## Troubleshooting
- If `ImportError` mentions relative imports:
  - ensure you are building from `scripts/ui_entrypoint.py`, not `src/mc_ws_dl_t/ui.py`.
- If build fails after dependency changes:
  - reinstall dependencies from `requirements-lock.txt`.
- If UI launches but site fetching fails:
  - run smoke tests:
    - `.\scripts\run-smoke.ps1`
