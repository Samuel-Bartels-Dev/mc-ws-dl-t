# CLI Reference

## Command Name

- Entry script: `mc-download`
- Compatibility alias: `mc-scrape`
- Module form: `python -m mc_ws_dl_t`
- UI command: `mc-ui`

## Syntax

```text
mc-download [options] <url>
```

## Positional Arguments

- `url`: target chapter URL to download.

## Options

- `--browser {chrome,firefox}`: browser for dynamic mode.
- `--prefer-dynamic`: force dynamic fetch before static.
- `--timeout-seconds <int>`: request/page-load timeout.
- `--wait-seconds <int>`: delay after dynamic page load.
- `--retries <int>`: retry attempts for static HTTP path.
- `--output <path>`: write JSON output file.
- `--image-dir <path>`: download parsed image files into this base folder.
- `--log-file <path>`: write a persistent log file.
- `--log-level {DEBUG,INFO,WARNING,ERROR}`: logging verbosity.
- `--force-parser {auto,generic,manganato,mangadex,mangatown,webtoons}`: parser selection override.

## Common Examples

Basic run:

```powershell
mc-download "https://example.com/chapter-1"
```

Dynamic-first run:

```powershell
mc-download "https://example.com/chapter-1" --prefer-dynamic --browser chrome
```

Output + logging:

```powershell
mc-download "https://example.com/chapter-1" --output .\output\chapter-1.json --log-file .\logs\run.log --log-level INFO
```

Download images:

```powershell
mc-download "https://example.com/chapter-1" --image-dir .\downloads
```

Force a parser manually:

```powershell
mc-download "https://m.mangatown.com/manga/example/chapter_1" --force-parser mangatown
```

## Exit Codes

- `0`: success
- `1`: fetch failure or unrecoverable runtime error
