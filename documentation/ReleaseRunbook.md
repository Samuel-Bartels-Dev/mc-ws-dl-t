# Release Runbook

Use this checklist before shipping updates to operators.

## 1. Sync and Clean State
1. Confirm branch and working tree:
   - `git branch --show-current`
   - `git status`
2. Ensure docs and runbooks reflect behavior changes.

## 2. Quality Gates
1. Compile check:
   - `python -m compileall src scripts`
2. Unit tests:
   - `pytest -q`
3. Optional quality checks:
   - `.\scripts\run-quality.ps1`

## 3. Smoke Validation
1. Run all adapters:
   - `.\scripts\run-smoke.ps1`
2. If failures occur:
   - verify if failures are environment/network related
   - update `tests/smoke_urls.json` when source URLs drift
3. Record results:
   - update `docs/dev/SMOKE_TEST_RESULTS.md`

## 4. UI + Workflow Validation
1. Launch UI:
   - `.\scripts\run-ui.ps1`
2. Validate:
   - series load
   - chapter selection and range selection
   - queue start/pause/resume/cancel
   - retry failed chapters
   - log panel and progress bars

## 5. Build Windows EXE
1. Run build:
   - `.\scripts\build-ui-exe.ps1`
2. Launch artifact:
   - `.\dist\mc-ui.exe`
3. Verify parser workflow from EXE.

## 6. Release Documentation
1. Ensure these are current:
   - `README.md`
   - `documentation/SetupAndOperations.md`
   - `documentation/UIAndExeRunbook.md`
   - `documentation/SmokeTestingRunbook.md`
   - `documentation/SecurityHardeningRunbook.md`
   - `docs/BUILD_WINDOWS_EXE.md`

## 7. Final Commit Hygiene
1. Use focused commit messages by area:
   - `ui: ...`
   - `test: ...`
   - `security: ...`
   - `docs: ...`
2. Avoid bundling unrelated changes in one commit.
