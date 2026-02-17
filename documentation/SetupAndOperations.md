# Setup and Operations

## Prerequisites

- Windows PowerShell
- Python 3.10+
- Internet access for package installation

## First-Time Setup

From project root (`mc-ws-dl-t`):

```powershell
.\bootstrap.ps1
```

Optional dynamic dependencies (Selenium):

```powershell
.\bootstrap.ps1 -InstallDynamic
```

## Daily Run Commands

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

or:

```powershell
.\scripts\run-tests.ps1
```

Run CLI against a page:

```powershell
.\.venv\Scripts\python.exe -m mc_ws_dl_t "https://example.com"
```

Write JSON output:

```powershell
.\.venv\Scripts\python.exe -m mc_ws_dl_t "https://example.com" --output .\output\result.json
```

Download image files:

```powershell
.\.venv\Scripts\python.exe -m mc_ws_dl_t "https://example.com" --image-dir .\downloads
```

## Development Checks

Lint:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
```

Type checks:

```powershell
.\.venv\Scripts\python.exe -m mypy src
```

or:

```powershell
.\scripts\run-quality.ps1
```

Smoke test:

```powershell
.\scripts\run-smoke.ps1 -Url "https://example.com"
```

Launch desktop UI:

```powershell
.\scripts\run-ui.ps1
```

## Mangatown Series Workflow (UI)

1. Enter series URL in `Chapter URL`:
   - Example: `https://m.mangatown.com/manga/tales_of_demons_and_gods`
2. Set `Image folder` to your manga library base path.
3. Click `Load Chapters` to parse all available chapters.
4. In `Series Chapters`, multi-select the chapters you want.
5. Click `Download Selected CBZ`.
6. Tool writes:
   - chapter image folders under `<series>/chapters/`
   - `.cbz` files under `<series>/cbz/`
   - history file `.mc_ws_dl_history.json` under the series root

## Build Artifacts

```powershell
.\.venv\Scripts\python.exe -m pip install build
.\.venv\Scripts\python.exe -m build
```

Build output goes to `dist/`.

Build standalone UI EXE:

```powershell
.\scripts\build-ui-exe.ps1
```

## VS Code Notes

- The bootstrap script writes `.vscode/settings.json` and points VS Code to `.venv`.
- If interpreter is not auto-selected, manually select `.venv\Scripts\python.exe`.
