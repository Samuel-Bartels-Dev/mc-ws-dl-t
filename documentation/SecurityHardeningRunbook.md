# Security Hardening Runbook

This runbook documents practical safety rules added to download/output handling.

## Scope
- Output directory safety
- Chapter temp file handling
- Path traversal prevention
- Dependency/config hygiene

## Path Safety Rules
- All series output paths must remain under the selected library root.
- All image output paths must remain under the selected output directory.
- All chapter temp output paths must remain under the chapter temp root.
- Out-of-root files are rejected or skipped.

Core implementation:
- `src/mc_ws_dl_t/core.py`

## Why This Matters
- Chapter titles and remote payload data are untrusted inputs.
- Unsafe path joins can write outside expected folders.
- Boundary checks prevent accidental or malicious path escape.

## Temp File Lifecycle
- Batch chapter downloads use per-chapter temp folders.
- Temp folders are cleaned after success/failure.
- Empty temp root is removed when possible.

## Logging Safety
- Structured logs with timestamps and levels are kept.
- No secrets are intentionally logged.
- UI logs are still mirrored to file for support diagnostics.

## Dependency Hygiene
- Runtime list: `requirements.txt`
- Reproducible lock-style list: `requirements-lock.txt`
- Local environment template: `.env.example`
- Ignore local secrets in git:
  - `.env`
  - `.env.*`
  - keep `.env.example`

## Verification Checklist
1. Run compile check:
   - `python -m compileall src scripts`
2. Run tests:
   - `pytest -q`
3. Run smoke matrix:
   - `.\scripts\run-smoke.ps1`
4. Confirm outputs remain inside selected library folder during UI/CLI runs.
