# Smoke Test Results

## Run Metadata
- Date: 2026-02-22
- Branch: `Dev`
- Command:

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke_test_sites.py --max-seconds-per-site 60
```

## Console Output (Example)

```text
[INFO] (1/4) Testing site 'manganato'...
[FAIL] manganato | images=0 | elapsed=1.9s | https://manganato.com/manga-aa951609/chapter-1 -> Redirected to unexpected host 'spinzywheel.com'. | https://mangakakalot.com/chapter/rg924299/chapter_1 -> Redirected to unexpected host 'spinzywheel.com'.
[INFO] (2/4) Testing site 'mangadex'...
[FAIL] mangadex | images=0 | elapsed=2.3s | https://mangadex.org/chapter/6f8f36ea-2f6f-4f84-95d4-3e860f6a264f -> HTTPSConnectionPool(host='mangadex.org', port=443): Max retries exceeded with url: /chapter/6f8f36ea-2f6f-4f84-95d4-3e860f6a264f (Caused by ResponseError('too many 503 error responses')) | https://mangadex.org/chapter/9f4fbd3f-c5f9-4af4-b0bb-1183d12c90eb -> HTTPSConnectionPool(host='mangadex.org', port=443): Max retries exceeded with url: /chapter/9f4fbd3f-c5f9-4af4-b0bb-1183d12c90eb (Caused by ResponseError('too many 503 error responses'))
[INFO] (3/4) Testing site 'mangatown'...
[PASS] mangatown | images=75 | elapsed=1.0s | Parsed 'Tower of God 652.0' with 75 image URL(s).
[INFO] (4/4) Testing site 'webtoons'...
[PASS] webtoons | images=1 | elapsed=3.5s | Parsed '[Season 1] Ep. 0 | Tower of God' with 1 image URL(s).

Smoke Test Summary
------------------
Total: 4 | Passed: 2 | Failed: 2
- FAIL manganato
- FAIL mangadex
- PASS mangatown | chapter=https://m.mangatown.com/manga/tower_of_god/c652/
- PASS webtoons | chapter=https://www.webtoons.com/en/fantasy/tower-of-god/season-1-ep-0/viewer?title_no=95&episode_no=1
```

## Notes
- `manganato` failed in this environment because the configured sample URLs redirected to a non-target host.
- `mangadex` failed in this environment due repeated HTTP 503 responses.
- Smoke URL samples are configurable in `tests/smoke_urls.json`.
