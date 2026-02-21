# MC-WS-DL-T Documentation

This folder contains the full documentation set for the manga/comic downloader project.

## What To Read First

- `TechnicalOverview.md`: architecture and module design.
- `SetupAndOperations.md`: install, run, test, build, and day-to-day workflow.
- `UIAndExeRunbook.md`: quick runbook for launching UI and building `dist\mc-ui.exe`.
- `SmokeTestingRunbook.md`: per-site smoke testing flow and failure triage.
- `SecurityHardeningRunbook.md`: path safety and output-boundary protections.
- `ReleaseRunbook.md`: pre-release checklist for tests, smoke, and EXE build.
- `CliReference.md`: command options and examples.
- `MaintenanceGuide.md`: support playbook, logging, troubleshooting, and update process.

## Legacy Comparison

- `ChangeLog-v1-to-v2.md`: what improved from `deprecated/web-scrapper-main` to this v2 rebuild.

## Suggested Reading Order

- Start with `SetupAndOperations.md` for daily commands.
- Use `CliReference.md` when running custom download jobs.
- Use `SmokeTestingRunbook.md` when validating site adapter health.
- Use `SecurityHardeningRunbook.md` when touching core write/download logic.
- Use `ReleaseRunbook.md` before shipping a build.
- Use `MaintenanceGuide.md` when troubleshooting or changing internals.
