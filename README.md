# MC-WS-DL-T (Manga/Comic Web Downloader Tool)

MC-WS-DL-T is the modernized v2 rebuild of the older project in `deprecated/web-scrapper-main`.

## What Changed

- Moved from loose scripts to a proper Python package layout (`src/`, `tests/`, `pyproject.toml`).
- Added a usable CLI entry point: `mc-download` (and compatibility alias `mc-scrape`).
- Added site parser plugin architecture (domain-based parser dispatch + generic fallback).
- Added image downloader support to save parsed chapter images to disk.
- Added structured logging, retries, and cleaner error handling.
- Added tests for parser behavior and fetch strategy behavior.
- Added bootstrap workflow for `.venv` and VSCode.

## Project Layout

```text
mc-ws-dl-t/
  deprecated/              # Old archived version (untouched)
  documentation/           # Project docs
  scripts/                 # Repeatable helper commands
  src/mc_ws_dl_t/          # New v2 code
    parsers/               # Site-specific parser plugins
  tests/                   # Unit tests
  pyproject.toml           # Packaging/dependencies/scripts
  bootstrap.ps1            # One-command Windows setup
```

## Quick Start (Windows + VSCode)

From `mc-ws-dl-t`:

```powershell
.\bootstrap.ps1
```

Then in VSCode:

- `Ctrl+Shift+P` -> `Python: Select Interpreter`
- choose `.venv\Scripts\python.exe` if not auto-selected

## Documentation Pack

- `documentation/README.md`: doc index and reading order
- `documentation/TechnicalOverview.md`: architecture and data flow
- `documentation/SetupAndOperations.md`: setup/run/test/build instructions
- `documentation/UIAndExeRunbook.md`: launch UI and build standalone `dist\mc-ui.exe`
- `documentation/CliReference.md`: command option reference
- `documentation/MaintenanceGuide.md`: support and troubleshooting workflow
- `documentation/ChangeLog-v1-to-v2.md`: upgrade summary from deprecated version

## Usage

Basic run:

```powershell
mc-download "https://example.com/chapter-1"
```

Save JSON output:

```powershell
mc-download "https://example.com/chapter-1" --output .\output\chapter-1.json
```

Download parsed images to a folder:

```powershell
mc-download "https://example.com/chapter-1" --image-dir .\downloads
```

Force dynamic mode:

```powershell
mc-download "https://mangakakalot.com/some-page" --prefer-dynamic --browser chrome
```

Force a specific parser plugin:

```powershell
mc-download "https://m.mangatown.com/manga/some-series/chapter_1" --force-parser mangatown
```

Series chapter discovery + download (UI):

- Paste a Mangatown series URL (example: `https://m.mangatown.com/manga/tales_of_demons_and_gods`)
- Click `Load Chapters`
- Multi-select chapters in `Series Chapters`
- Use chapter filter: `All chapters`, `Downloaded only`, or `Not downloaded`
- Click `Start Queue` to build CBZs in batch
- Optional queue controls: `Pause`, `Resume`, `Cancel`, and `Retry Failed`
- Output structure is saved in your selected image folder:
  - `<library>/<series>/cbz/<chapter>.cbz`
  - `<library>/<series>/.mc_ws_dl_history.json` (download history)
  - Chapter image folders are temporary and removed after CBZ is created.

## Desktop UI

Launch with script:

```powershell
.\scripts\run-ui.ps1
```

or directly:

```powershell
.\.venv\Scripts\mc-ui.exe
```

Build standalone UI EXE:

```powershell
.\scripts\build-ui-exe.ps1
```

UI defaults:

- Logs are auto-saved to `./logs` (one session file per launch).
- `Debug JSON` tab and JSON copy/save controls are available via `Show debug JSON tools`.
- `Pop Out Logs` opens a larger live log window.

## Run Tests

```powershell
.\scripts\run-tests.ps1
```

## Run Quality Checks

```powershell
.\scripts\run-quality.ps1
```

## Run Quick Smoke Test

```powershell
.\scripts\run-smoke.ps1
```

Run smoke test for one site adapter:

```powershell
.\scripts\run-smoke.ps1 -Site mangatown
```

Direct Python invocation (more options):

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_test_sites.py --max-seconds-per-site 60
```

## Package Build

```powershell
python -m pip install build
python -m build
```

## Windows EXE Build

```powershell
.\scripts\build-ui-exe.ps1
```

Detailed runbook:
- `docs/BUILD_WINDOWS_EXE.md`
