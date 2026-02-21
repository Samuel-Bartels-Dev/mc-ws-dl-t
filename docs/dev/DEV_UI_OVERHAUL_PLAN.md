# DEV UI Overhaul Plan

## Branch + Scope
- Branch: `Dev`
- Repository: `mc-ws-dl-t`
- Goal: modernize UI safely, harden runtime behavior, and add a reliable per-site smoke test without breaking existing download/parser logic.

## Phase 1 Audit Findings

### Entry points (CLI/UI)
- CLI module entrypoint: `src/mc_ws_dl_t/__main__.py` -> `mc_ws_dl_t.cli:main`
- CLI script entry points in `pyproject.toml`:
  - `mc-download`
  - `mc-scrape` (alias)
- UI script entry point in `pyproject.toml`:
  - `mc-ui` -> `mc_ws_dl_t.ui:main`
- EXE build path:
  - PyInstaller spec: `mc-ui.spec`
  - Build helper: `scripts/build-ui-exe.ps1`
  - PyInstaller source entrypoint: `scripts/ui_entrypoint.py`

### Site adapters/plugins model
- Plugin registry: `src/mc_ws_dl_t/parsers/registry.py`
- Parser plugin type: `src/mc_ws_dl_t/parsers/base.py` (`ParserPlugin`)
- Supported parser names/domains:
  - `manganato` (also handles `mangakakalot.com`)
  - `mangadex`
  - `mangatown`
  - `webtoons`
- Generic fallback parser: `src/mc_ws_dl_t/parser.py`

### Chapter discovery + chapter parsing
- Per-page parse dispatch:
  - `parse_for_url(...)` in `src/mc_ws_dl_t/parsers/registry.py`
- Series chapter discovery:
  - `discover_series(...)` in `src/mc_ws_dl_t/core.py`
  - Currently implemented for `mangatown` series pages.
- Chapter image extraction:
  - Site-specific parsers under `src/mc_ws_dl_t/parsers/*.py`
  - Mangatown chapter-page expansion helper:
    - `fetch_chapter_image_urls(...)` in `src/mc_ws_dl_t/parsers/mangatown.py`
- Download orchestration:
  - `run_download(...)` in `src/mc_ws_dl_t/core.py`
  - Batch chapter queue + CBZ output:
    - `download_selected_chapters_as_cbz(...)` in `src/mc_ws_dl_t/core.py`

### Config + logging patterns
- Runtime config dataclass: `src/mc_ws_dl_t/config.py` (`ScraperConfig`)
- Logger setup helper: `src/mc_ws_dl_t/logging_utils.py`
- UI logging:
  - In-process queue log handler and file logging in `src/mc_ws_dl_t/ui.py`
- Download history storage:
  - `.mc_ws_dl_history.json` via `src/mc_ws_dl_t/history.py`

## UI Approach Choice
- Chosen approach: **keep Tkinter backend but modernize structure + presentation incrementally**.
- Why:
  - Lowest risk to existing workflows and threading model.
  - Already PyInstaller-friendly and working with current build scripts.
  - Avoids large framework migration risk (Qt re-platform would be a bigger behavior surface area change).
- Implementation direction:
  - Keep core logic (`core.py`, parser modules, fetcher) reusable and UI-agnostic.
  - Introduce a `gui/` package for UI-specific utilities/components and keep `ui.py` as compatibility entrypoint.
  - Add modern UX improvements (layout polish, progress bars, clearer action groups, validation feedback, log UX).

## Planned Changes by Phase

### Phase 2: UI modernization (safe refactor)
- Add `src/mc_ws_dl_t/gui/` package for UI-only helpers:
  - theme/style constants
  - input validation helpers
  - UI event/progress helpers
- Update `src/mc_ws_dl_t/ui.py`:
  - modernized toolbar/action grouping
  - clearer primary actions (Load, Start Queue, Pause, Resume, Cancel)
  - add overall/per-chapter progress indicators
  - improve validation for URL/folder/numeric fields
  - improve disabled states and error messaging
  - preserve all existing capabilities and backend calls

### Phase 3: smoke test runner
- Add `scripts/smoke_test_sites.py`:
  - enumerate supported parser plugins from registry
  - for each site use `tests/smoke_urls.json` sample URL(s)
  - fetch + parse one chapter and ensure at least one image URL extracted
  - print per-site PASS/FAIL summary
  - support:
    - `--site <name>`
    - `--max-seconds-per-site`
  - enforce safe networking defaults:
    - explicit user-agent
    - timeout
    - small retries
    - polite per-site delay
    - max-bytes response guardrail

### Phase 4: security/hardening
- Add safe path utilities in core path-write flows:
  - sanitize title/path components
  - prevent path traversal via resolved-path checks
  - ensure writes remain under intended output/library roots
- Improve temp handling for chapter processing:
  - per-chapter temporary folders with deterministic cleanup
- Logging hardening:
  - structured timestamped logs are already present; keep/standardize
  - avoid logging sensitive values (no secret logging additions)
- Dependency hygiene:
  - add curated `requirements.txt` / lock-style pin file
- Config/secrets hygiene:
  - add `.env.example`
  - update `.gitignore` for `.env` and smoke output artifacts

### Phase 5: quality + packaging/docs
- Add/update:
  - `docs/BUILD_WINDOWS_EXE.md`
  - README sections for UI, CLI, smoke tests
- Ensure UI EXE path still works (PyInstaller-friendly).
- Run checks:
  - `python -m compileall src scripts`
  - existing tests (`pytest`) where feasible
  - smoke test script run with captured output
- Document smoke run output in:
  - `docs/dev/SMOKE_TEST_RESULTS.md`

## Files/Modules Expected to Change
- UI and GUI:
  - `src/mc_ws_dl_t/ui.py`
  - new files under `src/mc_ws_dl_t/gui/`
- Core hardening:
  - `src/mc_ws_dl_t/core.py`
  - possibly `src/mc_ws_dl_t/fetcher.py` (only safe default improvements)
- Smoke test:
  - `scripts/smoke_test_sites.py`
  - `tests/smoke_urls.json`
- Packaging/docs:
  - `README.md`
  - `docs/BUILD_WINDOWS_EXE.md`
  - `mc-ui.spec` (if needed)
  - `.gitignore`
  - `requirements.txt` / lock companion
  - `docs/dev/SMOKE_TEST_RESULTS.md`

## Risks and Mitigations
- Risk: UI regressions from layout changes.
  - Mitigation: preserve existing callback paths and event queue threading; refactor in small steps.
- Risk: parser/network instability for smoke tests.
  - Mitigation: externalize sample URLs, bound runtime per site, keep polite retries and clear per-site diagnostics.
- Risk: path hardening could block valid writes.
  - Mitigation: add resolved-path checks only around intended-root writes and preserve existing output structure.
- Risk: EXE packaging breakage.
  - Mitigation: keep entrypoint stable, verify PyInstaller build script/spec after changes.

## Validation Plan
- Unit/static checks:
  - `python -m compileall src scripts`
  - `pytest -q`
- Smoke:
  - `python scripts/smoke_test_sites.py`
  - `python scripts/smoke_test_sites.py --site <name>`
- Packaging:
  - `scripts/build-ui-exe.ps1`
  - launch `dist/mc-ui.exe`
