# Change Log: Legacy v1 to Modern v2

## Snapshot

This project replaces `deprecated/web-scrapper-main` with a structured and production-ready baseline.

## Key Improvements

- Migrated from loose scripts to package-based architecture.
- Added clean command-line interface (`mc-download`, with `mc-scrape` alias).
- Added robust fetch strategy (static + dynamic + fallback).
- Added parser plugin architecture for site-specific manga/comic extraction.
- Added direct image downloader support (saves chapter pages to disk).
- Added Mangatown series chapter discovery with multi-select UI workflow.
- Added chapter-to-CBZ packaging and per-series download history tracking.
- Added structured logging and clearer error handling.
- Added repeatable bootstrap flow for developer setup.
- Added automated tests for core parsing and fetch decision logic.

## Operational Gains

- Faster team onboarding through one-command setup.
- Lower support effort with predictable logs and clearer failures.
- Better change safety due to module separation and test coverage.
- Easier future expansion for site-specific parsing rules.

## Legacy Gaps Addressed

- Missing or partial modules are now fully implemented.
- Empty test scaffolding replaced with useful validation tests.
- Inconsistent execution flow replaced by a single orchestrated entrypoint.

## Current Scope

v2 currently focuses on stable fetch + parse foundations. Additional source-specific extraction can now be added incrementally without redesigning the project.
