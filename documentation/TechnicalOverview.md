# Technical Overview

## Architecture

The project follows a modern Python package layout:

- `src/mc_ws_dl_t/cli.py`: command-line entry and orchestration.
- `src/mc_ws_dl_t/ui.py`: desktop UI entrypoint and threaded run orchestration.
- `src/mc_ws_dl_t/core.py`: shared download workflow used by CLI and UI.
- `src/mc_ws_dl_t/fetcher.py`: static/dynamic page retrieval and fallback logic.
- `src/mc_ws_dl_t/parser.py`: generic parser fallback and extraction utilities.
- `src/mc_ws_dl_t/parsers/`: site-specific parser plugins and parser registry.
- `src/mc_ws_dl_t/config.py`: runtime config defaults and domain strategy.
- `src/mc_ws_dl_t/logging_utils.py`: standardized logger setup.

## Data Flow

1. CLI parses runtime options.
2. Config object is built.
3. Fetch strategy is selected (dynamic-first or static-first).
4. HTML is returned.
5. Parser registry chooses parser plugin by URL domain (or forced parser).
6. Selected parser extracts title and image URLs.
7. Optional image downloader saves files to disk.
8. Final payload is printed and optionally written to JSON.
9. Optional series workflow discovers chapters, downloads selected chapters, and builds CBZ files.

## Parser Plugin System

- Registry path: `src/mc_ws_dl_t/parsers/registry.py`
- Current plugins:
  - `manganato` (`manganato.com`, `mangakakalot.com`)
  - `mangadex` (`mangadex.org`)
  - `mangatown` (`m.mangatown.com`, `mangatown.com`)
  - `webtoons` (`webtoons.com`)
- Fallback parser: `generic` (`src/mc_ws_dl_t/parser.py`)

### Series + CBZ Pipeline

- Series discovery function: `discover_series(...)` in `src/mc_ws_dl_t/core.py`
- Selected chapter downloader: `download_selected_chapters_as_cbz(...)` in `src/mc_ws_dl_t/core.py`
- History tracking file per series: `.mc_ws_dl_history.json`
- CBZ packaging: chapter image sequence zipped to `<series>/cbz/<chapter>.cbz`

### Why This Structure

- Site-specific selectors stay isolated from core app flow.
- New sites can be added without rewriting CLI or fetch logic.
- Parser troubleshooting is easier because selected parser name is logged and returned in output.

## Fetch Strategy

- Static fetch is default for speed.
- Dynamic fetch is used first when:
  - `--prefer-dynamic` is specified, or
  - URL matches configured dynamic domains.
- If one path fails, fallback path is attempted before exiting.

## Logging Model

- Console logging is always enabled.
- File logging is optional via `--log-file`.
- Standardized format includes timestamp and level for triage.
- Image download logs include per-image progress and final success/failure counts.

## Test Coverage

Current tests focus on deterministic logic:

- Dynamic domain detection (`test_fetcher.py`).
- Title extraction and image URL normalization (`test_parser.py`).
- Parser registry + plugin dispatch behavior (`test_parser_registry.py`).

## Design Principles

- Keep scraping logic modular and testable.
- Keep CLI thin and orchestration-focused.
- Prefer readable error handling over silent failure.
- Keep defaults practical for Windows-based workflows.
