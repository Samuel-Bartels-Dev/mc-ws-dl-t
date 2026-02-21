import json
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Callable, Mapping, Sequence

from .config import ScraperConfig
from .fetcher import build_session
from .fetcher import FetchError, fetch_page
from .history import is_chapter_downloaded, load_history, mark_chapter_downloaded, save_history
from .parsers import resolve_parser_for_url
from .parsers import mangatown
from .parsers import parse_for_url


@dataclass(slots=True)
class DownloadOptions:
    # Target chapter URL to fetch and parse.
    url: str
    # Browser only matters for dynamic mode.
    browser: str = "chrome"
    # Force dynamic path first when needed.
    prefer_dynamic: bool = False
    # HTTP / page load timeout.
    timeout_seconds: int = 15
    # Extra dynamic wait for JS-heavy pages.
    wait_seconds: int = 5
    # Static HTTP retry attempts.
    retries: int = 3
    # Parser override mode.
    force_parser: str = "auto"
    # Optional payload file path.
    output: Path | None = None
    # Optional image download base folder.
    image_download_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class SeriesChapter:
    title: str
    url: str
    release: str = ""
    chapter_key: str = ""


@dataclass(frozen=True, slots=True)
class SeriesInfo:
    title: str
    url: str
    parser: str
    cover_url: str | None
    chapters: tuple[SeriesChapter, ...]


def _slugify(value: str) -> str:
    # Filesystem-safe chapter folder name while keeping the title readable.
    cleaned = "".join(char if char.isalnum() or char in (" ", "-", "_") else " " for char in value)
    slug = "-".join(cleaned.strip().split())
    return slug[:96] or "untitled-chapter"


def _resolve_path(path: Path) -> Path:
    # Resolve without requiring existence so we can validate future write locations safely.
    return path.expanduser().resolve(strict=False)


def _ensure_path_within_root(root: Path, candidate: Path, label: str) -> Path:
    # This prevents path traversal by forcing every write target to stay inside one trusted root.
    resolved_root = _resolve_path(root)
    resolved_candidate = _resolve_path(candidate)
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise RuntimeError(f"{label} escapes the selected output directory: {resolved_candidate}")
    return resolved_candidate


def _safe_join_root(root: Path, child_name: str, label: str) -> Path:
    return _ensure_path_within_root(root, root / child_name, label)


def _build_series_root(base_library_dir: Path, series_title: str) -> Path:
    # Series folders must always stay under the chosen library root.
    return _safe_join_root(base_library_dir, _slugify(series_title), "Series folder path")


def build_series_root_path(base_library_dir: Path, series_title: str) -> Path:
    return _build_series_root(base_library_dir, series_title)


def _build_image_filename(index: int, image_url: str) -> str:
    # Preserve extension when possible; default to jpg for extensionless URLs.
    path = urlparse(image_url).path
    suffix = Path(path).suffix.lower()
    if not suffix or len(suffix) > 6:
        suffix = ".jpg"
    return f"page_{index:04d}{suffix}"


def download_images(
    image_urls: Sequence[str],
    output_dir: Path,
    config: ScraperConfig,
    logger: logging.Logger,
    referer: str | None = None,
) -> dict[str, Any]:
    # Downloads image URLs with retries and writes a deterministic numbered sequence.
    output_dir = _resolve_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(image_urls)
    downloaded_files: list[str] = []
    failures: list[dict[str, str]] = []

    if total == 0:
        logger.info("No image URLs available for download.")
        return {
            "output_dir": str(output_dir),
            "attempted": 0,
            "downloaded": 0,
            "failed": 0,
            "files": [],
            "failures": [],
        }

    session = build_session(config)
    try:
        for index, image_url in enumerate(image_urls, start=1):
            filename = _build_image_filename(index=index, image_url=image_url)
            output_path = _ensure_path_within_root(
                output_dir,
                output_dir / filename,
                "Image file path",
            )
            logger.info("Downloading image %s/%s: %s", index, total, image_url)
            try:
                request_headers: dict[str, str] | None = {"Referer": referer} if referer else None
                response = session.get(
                    image_url,
                    timeout=config.timeout_seconds,
                    stream=True,
                    headers=request_headers,
                )
                response.raise_for_status()
                with output_path.open("wb") as file_handle:
                    for chunk in response.iter_content(chunk_size=128 * 1024):
                        if chunk:
                            file_handle.write(chunk)
                downloaded_files.append(str(output_path))
            except Exception as exc:
                # Keep the run going even if a few image URLs fail.
                failures.append({"url": image_url, "error": str(exc)})
                logger.warning("Failed image download: %s | %s", image_url, exc)
    finally:
        session.close()

    summary = {
        "output_dir": str(output_dir),
        "attempted": total,
        "downloaded": len(downloaded_files),
        "failed": len(failures),
        "files": downloaded_files,
        "failures": failures,
    }
    logger.info(
        "Image download complete. attempted=%s downloaded=%s failed=%s dir=%s",
        summary["attempted"],
        summary["downloaded"],
        summary["failed"],
        summary["output_dir"],
    )
    return summary


def download_images_from_payload(
    payload: Mapping[str, Any],
    output_base_dir: Path,
    config: ScraperConfig,
    logger: logging.Logger,
) -> dict[str, Any]:
    output_base_dir = _resolve_path(output_base_dir)
    output_base_dir.mkdir(parents=True, exist_ok=True)
    image_urls_raw = payload.get("image_urls")
    image_urls = [str(url) for url in image_urls_raw] if isinstance(image_urls_raw, list) else []
    title = str(payload.get("title", "untitled-chapter"))
    source_url = str(payload.get("source_url", "")) or None
    chapter_dir = _safe_join_root(output_base_dir, _slugify(title), "Chapter output folder path")
    return download_images(
        image_urls=image_urls,
        output_dir=chapter_dir,
        config=config,
        logger=logger,
        referer=source_url,
    )


def discover_series(
    series_url: str,
    config: ScraperConfig,
    logger: logging.Logger,
    prefer_dynamic: bool = False,
    browser: str = "chrome",
) -> SeriesInfo:
    # Series discovery currently supports Mangatown's mobile site layout.
    parser_plugin = resolve_parser_for_url(series_url)
    if not parser_plugin or parser_plugin.name != "mangatown":
        raise RuntimeError("Series discovery is currently supported for m.mangatown.com URLs.")

    try:
        html = fetch_page(
            series_url,
            config=config,
            logger=logger,
            prefer_dynamic=prefer_dynamic,
            browser=browser,
        )
    except FetchError as exc:
        raise RuntimeError(f"Failed to fetch series page: {exc}") from exc

    chapters = tuple(
        SeriesChapter(
            title=chapter.title,
            url=chapter.url,
            release=chapter.release,
            chapter_key=chapter.chapter_key,
        )
        for chapter in mangatown.parse_series_chapters(html, base_url=series_url)
    )
    if not chapters:
        raise RuntimeError("No chapters found on the series page.")

    title = mangatown.extract_series_title(html)
    cover_url = mangatown.extract_series_cover_url(html, base_url=series_url)
    return SeriesInfo(
        title=title,
        url=series_url,
        parser="mangatown",
        cover_url=cover_url,
        chapters=chapters,
    )


def _download_single_file(
    file_url: str,
    output_path: Path,
    config: ScraperConfig,
    logger: logging.Logger,
    referer: str | None = None,
) -> bool:
    session = build_session(config)
    try:
        request_headers: dict[str, str] | None = {"Referer": referer} if referer else None
        response = session.get(file_url, timeout=config.timeout_seconds, stream=True, headers=request_headers)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if chunk:
                    file_handle.write(chunk)
        logger.info("Downloaded file: %s", output_path)
        return True
    except Exception as exc:
        logger.warning("Failed file download: %s | %s", file_url, exc)
        return False
    finally:
        session.close()


def create_cbz_from_files(
    image_files: Sequence[str],
    cbz_path: Path,
    logger: logging.Logger,
    cover_file: Path | None = None,
    allowed_root: Path | None = None,
) -> Path:
    cbz_path = _resolve_path(cbz_path)
    cbz_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_allowed_root = _resolve_path(allowed_root) if allowed_root else None

    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if cover_file and cover_file.exists():
            archive.write(cover_file, arcname=f"0000_cover{cover_file.suffix.lower() or '.jpg'}")
        for file_path in sorted((Path(path) for path in image_files), key=lambda path: path.name):
            resolved_file_path = _resolve_path(file_path)
            if resolved_allowed_root is not None:
                if (
                    resolved_file_path != resolved_allowed_root
                    and resolved_allowed_root not in resolved_file_path.parents
                ):
                    logger.warning("Skipping out-of-root chapter file: %s", resolved_file_path)
                    continue

            if resolved_file_path.exists():
                archive.write(resolved_file_path, arcname=resolved_file_path.name)
    logger.info("CBZ created: %s", cbz_path)
    return cbz_path


def _cleanup_chapter_temp_dir(
    chapter_temp_dir: Path | None,
    chapters_root: Path,
    logger: logging.Logger,
) -> None:
    # Chapter image files are temporary once CBZ is created.
    if chapter_temp_dir and chapter_temp_dir.exists():
        shutil.rmtree(chapter_temp_dir, ignore_errors=False)
        logger.info("Removed temporary chapter files: %s", chapter_temp_dir)

    # Keep the series folder tidy by removing empty temporary roots.
    if chapters_root.exists():
        try:
            if not any(chapters_root.iterdir()):
                chapters_root.rmdir()
                logger.info("Removed empty chapter temp root: %s", chapters_root)
        except Exception as exc:
            logger.debug("Could not remove chapter temp root: %s | %s", chapters_root, exc)


def download_selected_chapters_as_cbz(
    series_info: SeriesInfo,
    selected_chapters: Sequence[SeriesChapter],
    library_root_dir: Path,
    config: ScraperConfig,
    logger: logging.Logger,
    browser: str = "chrome",
    prefer_dynamic: bool = False,
    retry_per_chapter: int = 0,
    should_cancel: Callable[[], bool] | None = None,
    wait_if_paused: Callable[[], None] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if retry_per_chapter < 0:
        retry_per_chapter = 0

    def emit_progress(event: str, **data: Any) -> None:
        if progress_callback:
            progress_callback({"event": event, **data})

    library_root_dir = _resolve_path(library_root_dir)
    series_root = _build_series_root(library_root_dir, series_info.title)
    chapters_dir = _safe_join_root(series_root, "chapters", "Chapter temp root path")
    cbz_dir = _safe_join_root(series_root, "cbz", "CBZ output path")
    series_root.mkdir(parents=True, exist_ok=True)
    chapters_dir.mkdir(parents=True, exist_ok=True)

    history = load_history(series_root)
    history["series_url"] = series_info.url
    history["series_title"] = series_info.title
    history["parser"] = series_info.parser

    cover_file: Path | None = None
    if series_info.cover_url:
        candidate = series_root / "cover.jpg"
        if candidate.exists() or _download_single_file(
            series_info.cover_url,
            candidate,
            config,
            logger,
            referer=series_info.url,
        ):
            cover_file = candidate

    total_chapters = len(selected_chapters)
    emit_progress("batch_start", total=total_chapters, series=series_info.title)

    summary: list[dict[str, Any]] = []
    canceled = False
    for index, chapter in enumerate(selected_chapters, start=1):
        if wait_if_paused:
            wait_if_paused()
        if should_cancel and should_cancel():
            canceled = True
            emit_progress("batch_canceled", completed=index - 1, total=total_chapters)
            logger.info("Batch canceled before chapter %s", chapter.title)
            break

        if is_chapter_downloaded(history, chapter.url):
            existing = history["chapters"][chapter.url]
            logger.info("Skipping already-downloaded chapter: %s", chapter.title)
            skipped_result = {
                "title": chapter.title,
                "url": chapter.url,
                "status": "skipped",
                "cbz_path": existing.get("cbz_path", ""),
                "pages": int(existing.get("page_count", 0)),
            }
            summary.append(skipped_result)
            emit_progress(
                "chapter_skipped",
                index=index,
                total=total_chapters,
                title=chapter.title,
                url=chapter.url,
                cbz_path=skipped_result["cbz_path"],
            )
            continue

        emit_progress(
            "chapter_start",
            index=index,
            total=total_chapters,
            title=chapter.title,
            url=chapter.url,
        )
        logger.info("Downloading chapter: %s | %s", chapter.title, chapter.url)

        chapter_success = False
        for attempt in range(retry_per_chapter + 1):
            chapter_temp_dir: Path | None = None
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                canceled = True
                break

            try:
                chapter_temp_dir = Path(
                    tempfile.mkdtemp(
                        prefix="chapter_",
                        dir=str(chapters_dir),
                    )
                )
                options = DownloadOptions(
                    url=chapter.url,
                    browser=browser,
                    prefer_dynamic=prefer_dynamic,
                    timeout_seconds=config.timeout_seconds,
                    wait_seconds=config.wait_seconds,
                    retries=config.retries,
                    force_parser="mangatown",
                    image_download_dir=chapter_temp_dir,
                    output=None,
                )
                payload = run_download(options, logger=logger)

                download_info = payload.get("download")
                if not isinstance(download_info, dict):
                    raise RuntimeError(f"Chapter did not produce download summary: {chapter.url}")
                output_dir_raw = download_info.get("output_dir")
                if isinstance(output_dir_raw, str) and output_dir_raw.strip():
                    if chapter_temp_dir is None:
                        raise RuntimeError("Chapter temp root was not initialized before output validation.")
                    _ensure_path_within_root(
                        chapter_temp_dir,
                        Path(output_dir_raw),
                        "Chapter temp output path",
                    )
                image_files_raw = download_info.get("files")
                image_files = [str(path) for path in image_files_raw] if isinstance(image_files_raw, list) else []
                if not image_files:
                    raise RuntimeError(f"No images downloaded for chapter: {chapter.url}")

                cbz_name = f"{_slugify(chapter.title)}.cbz"
                cbz_path = create_cbz_from_files(
                    image_files=image_files,
                    cbz_path=cbz_dir / cbz_name,
                    logger=logger,
                    cover_file=cover_file,
                    allowed_root=chapter_temp_dir,
                )
                mark_chapter_downloaded(
                    history=history,
                    chapter_url=chapter.url,
                    chapter_title=chapter.title,
                    cbz_path=cbz_path,
                    page_count=len(image_files),
                )
                try:
                    _cleanup_chapter_temp_dir(chapter_temp_dir=chapter_temp_dir, chapters_root=chapters_dir, logger=logger)
                except Exception as exc:
                    logger.warning("Temporary chapter cleanup failed: %s | %s", chapter.title, exc)

                result = {
                    "title": chapter.title,
                    "url": chapter.url,
                    "status": "downloaded",
                    "cbz_path": str(cbz_path),
                    "pages": len(image_files),
                    "attempts": attempt + 1,
                }
                summary.append(result)
                emit_progress(
                    "chapter_downloaded",
                    index=index,
                    total=total_chapters,
                    title=chapter.title,
                    url=chapter.url,
                    cbz_path=result["cbz_path"],
                    pages=result["pages"],
                    attempts=result["attempts"],
                )
                chapter_success = True
                break
            except Exception as exc:
                try:
                    _cleanup_chapter_temp_dir(chapter_temp_dir=chapter_temp_dir, chapters_root=chapters_dir, logger=logger)
                except Exception:
                    # Best-effort cleanup; the main error is reported below.
                    pass
                logger.warning(
                    "Chapter attempt failed (%s/%s): %s | %s",
                    attempt + 1,
                    retry_per_chapter + 1,
                    chapter.title,
                    exc,
                )
                if attempt < retry_per_chapter:
                    emit_progress(
                        "chapter_retry",
                        index=index,
                        total=total_chapters,
                        title=chapter.title,
                        url=chapter.url,
                        next_attempt=attempt + 2,
                    )
                    continue

                failed_result = {
                    "title": chapter.title,
                    "url": chapter.url,
                    "status": "failed",
                    "error": str(exc),
                    "attempts": attempt + 1,
                }
                summary.append(failed_result)
                emit_progress(
                    "chapter_failed",
                    index=index,
                    total=total_chapters,
                    title=chapter.title,
                    url=chapter.url,
                    error=str(exc),
                )
                break

        if canceled:
            emit_progress("batch_canceled", completed=index - (1 if chapter_success is False else 0), total=total_chapters)
            logger.info("Batch canceled during chapter processing.")
            break

    history["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    history_path = save_history(series_root, history)

    # Final cleanup pass for chapter temp root in case a previous attempt left it empty.
    try:
        _cleanup_chapter_temp_dir(chapter_temp_dir=None, chapters_root=chapters_dir, logger=logger)
    except Exception as exc:
        logger.debug("Final chapter temp cleanup skipped: %s", exc)

    failed_items = [item for item in summary if str(item.get("status")) == "failed"]
    skipped_items = [item for item in summary if str(item.get("status")) == "skipped"]
    downloaded_items = [item for item in summary if str(item.get("status")) == "downloaded"]

    emit_progress(
        "batch_complete",
        total=total_chapters,
        downloaded=len(downloaded_items),
        skipped=len(skipped_items),
        failed=len(failed_items),
        canceled=canceled,
    )

    return {
        "series_title": series_info.title,
        "series_root": str(series_root),
        "history_path": str(history_path),
        "results": summary,
        "downloaded_count": len(downloaded_items),
        "skipped_count": len(skipped_items),
        "failed_count": len(failed_items),
        "failed_urls": [str(item.get("url", "")) for item in failed_items],
        "canceled": canceled,
    }


def run_download(options: DownloadOptions, logger: logging.Logger) -> dict[str, Any]:
    # Keep runtime options in shared config so fetch functions stay consistent.
    config = ScraperConfig(
        timeout_seconds=options.timeout_seconds,
        wait_seconds=options.wait_seconds,
        retries=options.retries,
    )

    logger.info("Starting download for: %s", options.url)
    try:
        html = fetch_page(
            options.url,
            config=config,
            logger=logger,
            prefer_dynamic=options.prefer_dynamic,
            browser=options.browser,
        )
    except FetchError as exc:
        raise RuntimeError(f"Failed to fetch page: {exc}") from exc

    try:
        parsed, parser_name = parse_for_url(
            html,
            url=options.url,
            force_parser=options.force_parser,
        )
    except ValueError as exc:
        raise RuntimeError(f"Parser configuration error: {exc}") from exc

    # A series URL only has cover/metadata. Direct chapter image download needs a chapter URL.
    if parser_name == "mangatown" and mangatown.is_series_url(options.url):
        raise RuntimeError(
            "Series URL detected. Use 'Load Chapters' and 'Start Queue', or paste a chapter URL like /c###/."
        )

    payload: dict[str, Any] = {
        "source_url": options.url,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "parser": parser_name,
        **parsed.to_dict(),
    }

    # Mangatown chapter pages often list one image per HTML page. Expand to full chapter set.
    if parser_name == "mangatown" and mangatown.is_chapter_url(options.url):
        expanded_urls = mangatown.fetch_chapter_image_urls(
            chapter_url=options.url,
            config=config,
            logger=logger,
        )
        if expanded_urls:
            payload["image_urls"] = expanded_urls

    if options.image_download_dir:
        payload["download"] = download_images_from_payload(
            payload=payload,
            output_base_dir=options.image_download_dir,
            config=config,
            logger=logger,
        )

    if options.output:
        # File output is optional and only written when caller requests it.
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Wrote output: %s", options.output)

    logger.info("Parser used: %s", parser_name)
    logger.info("Title: %s", payload["title"])
    logger.info("Image URLs found: %s", len(payload["image_urls"]))
    return payload
