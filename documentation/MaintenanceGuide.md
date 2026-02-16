# Maintenance Guide

## Support Workflow

1. Reproduce issue with full command and `--log-level DEBUG`.
2. Capture terminal output and optional `--log-file` artifact.
3. Identify whether failure occurred in static or dynamic path.
4. Add/adjust tests before code changes when possible.
5. Re-run tests, lint, and type checks before release.

## Troubleshooting

### Python not found

- Validate with `python --version` or `py -3 --version`.
- Re-run `.\bootstrap.ps1` after installing Python.

### Selenium errors in dynamic mode

- Install optional deps: `.\bootstrap.ps1 -InstallDynamic`
- Ensure browser + driver compatibility.
- Confirm `--browser` matches installed browser.

### Static fetch blocked or fails

- Increase `--retries` and `--timeout-seconds`.
- Try `--prefer-dynamic` for JS-heavy pages.
- Validate URL accessibility outside the downloader.

### Empty/low image results

- Confirm target page actually renders `<img>` tags in HTML.
- Use dynamic mode if content is injected after page load.
- Extend parser plugin selectors for that source if needed.

### Chapter already downloaded / skipped unexpectedly

- Check series history file: `.mc_ws_dl_history.json` under the series folder.
- Remove a chapter entry from history if you want to force redownload.
- Confirm chapter URL matches exactly (history keys are chapter URLs).

## Safe Change Process

- Keep generic parser changes in `src/mc_ws_dl_t/parser.py`.
- Keep site-specific parser changes in `src/mc_ws_dl_t/parsers/<site>.py`.
- Keep parser routing changes in `src/mc_ws_dl_t/parsers/registry.py`.
- Keep request/driver changes isolated in `fetcher.py`.
- Keep CLI arguments backward compatible unless versioning is updated.
- Add test coverage for every new parsing rule.

## Adding a New Website Parser

1. Create `src/mc_ws_dl_t/parsers/<site>.py` with `DOMAINS` and `parse(html, base_url)` function.
2. Register the plugin in `src/mc_ws_dl_t/parsers/registry.py`.
3. Add tests in `tests/test_parser_registry.py` and a focused parser test file if needed.
4. Run `.\scripts\run-tests.ps1` and `.\scripts\run-quality.ps1`.

## Versioning Notes

- Update `pyproject.toml` and `src/mc_ws_dl_t/__init__.py` version together.
- Record notable changes in `documentation/ChangeLog-v1-to-v2.md` or future changelog docs.
