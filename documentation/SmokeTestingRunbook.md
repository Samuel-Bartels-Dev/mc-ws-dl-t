# Smoke Testing Runbook

This runbook validates that each supported site adapter can parse at least one chapter and return image URLs.

## Purpose
- Catch parser drift early.
- Detect host redirects, outages, and selector breakage.
- Provide one command for local validation and CI gating.

## Smoke Inputs
- Script: `scripts/smoke_test_sites.py`
- URL config: `tests/smoke_urls.json`

Do not hardcode site URLs in script code. Keep them in `tests/smoke_urls.json`.

## Commands

Run all adapters:

```powershell
.\scripts\run-smoke.ps1
```

Run one adapter:

```powershell
.\scripts\run-smoke.ps1 -Site mangatown
```

Run Python script directly:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_test_sites.py --max-seconds-per-site 60
```

Useful options:
- `--site <name>`
- `--max-seconds-per-site <int>`
- `--timeout-seconds <int>`
- `--retries <int>`
- `--delay-seconds <float>`

## Exit Code Rules
- `0` = all tested adapters passed.
- `1` = one or more adapters failed.
- `2` = invalid adapter argument (unknown `--site`).

## PASS Criteria Per Site
Each site must:
1. Fetch one chapter URL successfully.
2. Parse with the expected adapter.
3. Return at least one image URL.
4. Stay within time and response-size guardrails.

## Common Failures and Fixes

### Redirected to wrong host
- Symptom: `Redirected to unexpected host`.
- Action: update `tests/smoke_urls.json` with a valid source URL for that site.

### HTTP 503/429
- Symptom: retry exhaustion errors.
- Action: re-run later, increase `--max-seconds-per-site`, or adjust sample URLs.

### Zero images parsed
- Symptom: parser returned zero image URLs.
- Action: update site parser selectors in `src/mc_ws_dl_t/parsers/<site>.py` and add tests.

## Updating Sample URLs Safely
1. Update `tests/smoke_urls.json`.
2. Run single-site smoke until PASS.
3. Run full smoke matrix.
4. Record result updates in `docs/dev/SMOKE_TEST_RESULTS.md`.
