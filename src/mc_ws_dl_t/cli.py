import argparse
import json
from pathlib import Path

from .core import DownloadOptions, run_download
from .logging_utils import setup_logging
from .parsers import get_available_parser_names


def build_parser() -> argparse.ArgumentParser:
    # Keep CLI flags grouped here so users can run/help the tool without opening code internals.
    parser = argparse.ArgumentParser(
        prog="mc-download",
        description="Fetch a manga/comic page, parse image URLs, and optionally save JSON/images.",
    )
    parser.add_argument("url", help="Target chapter URL to download.")
    parser.add_argument(
        "--browser",
        default="chrome",
        choices=("chrome", "firefox"),
        help="Browser for dynamic mode.",
    )
    parser.add_argument(
        "--prefer-dynamic",
        action="store_true",
        help="Try dynamic rendering first.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=15,
        help="Request/page-load timeout.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=5,
        help="Wait time for JS rendering in dynamic mode.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="HTTP retry attempts for static fetch.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path.",
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        help="Optional folder to download parsed images into.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional log file path.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Console/file log verbosity.",
    )
    parser.add_argument(
        "--force-parser",
        default="auto",
        choices=tuple(get_available_parser_names()),
        help="Parser selection override. Default is auto by URL domain.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Parse arguments first so everything after this runs with one validated config source.
    parser = build_parser()
    args = parser.parse_args(argv)

    # One logger instance for the full run keeps console + file logs consistent.
    logger = setup_logging(level=args.log_level, log_file=args.log_file)

    # Shared options object keeps CLI and UI behavior consistent.
    options = DownloadOptions(
        url=args.url,
        browser=args.browser,
        prefer_dynamic=args.prefer_dynamic,
        timeout_seconds=args.timeout_seconds,
        wait_seconds=args.wait_seconds,
        retries=args.retries,
        force_parser=args.force_parser,
        output=args.output,
        image_download_dir=args.image_dir,
    )

    try:
        payload = run_download(options, logger=logger)
    except RuntimeError as exc:
        # Return code 1 makes this safe for scripts/CI to detect run failures.
        logger.error("%s", exc)
        return 1

    # Emit full payload to stdout so the command can be chained or redirected.
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0
