import logging
from pathlib import Path
from typing import Any

import pytest

from mc_ws_dl_t.config import ScraperConfig
from mc_ws_dl_t.core import (
    DownloadOptions,
    SeriesChapter,
    SeriesInfo,
    discover_series,
    download_selected_chapters_as_cbz,
    download_images_from_payload,
    run_download,
)
from mc_ws_dl_t.fetcher import FetchError
from mc_ws_dl_t.parser import ParsedPage


def _build_test_logger() -> logging.Logger:
    logger = logging.getLogger("mc_ws_dl_t.tests.core")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def test_run_download_success_writes_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_fetch_page(*args: object, **kwargs: object) -> str:
        return "<html><head><title>Test</title></head><body></body></html>"

    def fake_parse_for_url(*args: object, **kwargs: object) -> tuple[ParsedPage, str]:
        return ParsedPage(title="Test Chapter", image_urls=["https://cdn.example.com/1.jpg"]), "generic"

    monkeypatch.setattr("mc_ws_dl_t.core.fetch_page", fake_fetch_page)
    monkeypatch.setattr("mc_ws_dl_t.core.parse_for_url", fake_parse_for_url)

    output_file = tmp_path / "payload.json"
    options = DownloadOptions(
        url="https://example.com/chapter-1",
        output=output_file,
    )

    payload = run_download(options, logger=_build_test_logger())
    assert payload["source_url"] == "https://example.com/chapter-1"
    assert payload["parser"] == "generic"
    assert payload["title"] == "Test Chapter"
    assert payload["image_urls"] == ["https://cdn.example.com/1.jpg"]
    assert output_file.exists() is True


def test_run_download_wraps_fetch_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_page(*args: object, **kwargs: object) -> str:
        raise FetchError("boom")

    monkeypatch.setattr("mc_ws_dl_t.core.fetch_page", fake_fetch_page)

    options = DownloadOptions(url="https://example.com/chapter-1")
    with pytest.raises(RuntimeError, match="Failed to fetch page"):
        run_download(options, logger=_build_test_logger())


def test_run_download_includes_image_download_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_fetch_page(*args: object, **kwargs: object) -> str:
        return "<html><head><title>Test</title></head><body></body></html>"

    def fake_parse_for_url(*args: object, **kwargs: object) -> tuple[ParsedPage, str]:
        return ParsedPage(title="Test Chapter", image_urls=["https://cdn.example.com/1.jpg"]), "generic"

    def fake_download_images_from_payload(*args: object, **kwargs: object) -> dict[str, Any]:
        return {
            "output_dir": str(tmp_path / "Test-Chapter"),
            "attempted": 1,
            "downloaded": 1,
            "failed": 0,
            "files": [str(tmp_path / "Test-Chapter" / "page_0001.jpg")],
            "failures": [],
        }

    monkeypatch.setattr("mc_ws_dl_t.core.fetch_page", fake_fetch_page)
    monkeypatch.setattr("mc_ws_dl_t.core.parse_for_url", fake_parse_for_url)
    monkeypatch.setattr("mc_ws_dl_t.core.download_images_from_payload", fake_download_images_from_payload)

    options = DownloadOptions(
        url="https://example.com/chapter-1",
        image_download_dir=tmp_path,
    )

    payload = run_download(options, logger=_build_test_logger())
    assert "download" in payload
    download_summary = payload["download"]
    assert isinstance(download_summary, dict)
    assert download_summary["downloaded"] == 1


def test_download_images_from_payload_builds_title_subfolder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_download_images(*args: object, **kwargs: object) -> dict[str, Any]:
        captured["output_dir"] = kwargs["output_dir"]
        captured["image_urls"] = kwargs["image_urls"]
        return {
            "output_dir": str(kwargs["output_dir"]),
            "attempted": 2,
            "downloaded": 2,
            "failed": 0,
            "files": [],
            "failures": [],
        }

    monkeypatch.setattr("mc_ws_dl_t.core.download_images", fake_download_images)

    payload = {
        "title": "My Chapter: 01",
        "image_urls": ["https://cdn.example.com/1.jpg", "https://cdn.example.com/2.jpg"],
    }
    summary = download_images_from_payload(
        payload=payload,
        output_base_dir=tmp_path,
        config=None,  # type: ignore[arg-type]
        logger=_build_test_logger(),
    )
    assert summary["attempted"] == 2
    assert str(captured["output_dir"]).endswith("My-Chapter-01")
    assert captured["image_urls"] == payload["image_urls"]


def test_discover_series_returns_mangatown_series_info(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_page(*args: object, **kwargs: object) -> str:
        return "<html></html>"

    def fake_extract_series_title(*args: object, **kwargs: object) -> str:
        return "Tales of Demons and Gods"

    def fake_extract_series_cover_url(*args: object, **kwargs: object) -> str:
        return "https://cdn.example.com/cover.jpg"

    def fake_parse_series_chapters(*args: object, **kwargs: object) -> list[object]:
        return [
            type("Chapter", (), {"title": "C.2", "url": "https://m.mangatown.com/manga/x/c2/", "release": "", "chapter_key": "2"})(),
            type("Chapter", (), {"title": "C.1", "url": "https://m.mangatown.com/manga/x/c1/", "release": "", "chapter_key": "1"})(),
        ]

    def fake_resolve_parser_for_url(*args: object, **kwargs: object) -> object:
        return type("Plugin", (), {"name": "mangatown"})()

    monkeypatch.setattr("mc_ws_dl_t.core.fetch_page", fake_fetch_page)
    monkeypatch.setattr("mc_ws_dl_t.core.resolve_parser_for_url", fake_resolve_parser_for_url)
    monkeypatch.setattr("mc_ws_dl_t.core.mangatown.extract_series_title", fake_extract_series_title)
    monkeypatch.setattr("mc_ws_dl_t.core.mangatown.extract_series_cover_url", fake_extract_series_cover_url)
    monkeypatch.setattr("mc_ws_dl_t.core.mangatown.parse_series_chapters", fake_parse_series_chapters)

    info = discover_series(
        series_url="https://m.mangatown.com/manga/tales_of_demons_and_gods",
        config=ScraperConfig(),
        logger=_build_test_logger(),
    )
    assert info.title == "Tales of Demons and Gods"
    assert info.cover_url == "https://cdn.example.com/cover.jpg"
    assert len(info.chapters) == 2
    assert isinstance(info.chapters[0], SeriesChapter)


def test_run_download_rejects_mangatown_series_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_page(*args: object, **kwargs: object) -> str:
        return "<html><head><title>Series</title></head><body></body></html>"

    def fake_parse_for_url(*args: object, **kwargs: object) -> tuple[ParsedPage, str]:
        return ParsedPage(title="Series", image_urls=["https://cdn.example.com/cover.jpg"]), "mangatown"

    monkeypatch.setattr("mc_ws_dl_t.core.fetch_page", fake_fetch_page)
    monkeypatch.setattr("mc_ws_dl_t.core.parse_for_url", fake_parse_for_url)

    options = DownloadOptions(url="https://m.mangatown.com/manga/tales_of_demons_and_gods")
    with pytest.raises(RuntimeError, match="Series URL detected"):
        run_download(options, logger=_build_test_logger())


def test_download_selected_chapters_removes_temp_chapter_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chapter = SeriesChapter(
        title="C.1",
        url="https://m.mangatown.com/manga/demo/c1/",
        release="",
        chapter_key="1",
    )
    series = SeriesInfo(
        title="Demo Series",
        url="https://m.mangatown.com/manga/demo",
        parser="mangatown",
        cover_url=None,
        chapters=(chapter,),
    )

    def fake_run_download(options: DownloadOptions, logger: logging.Logger) -> dict[str, Any]:
        assert options.image_download_dir is not None
        chapter_dir = options.image_download_dir / "C-1"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        image_path = chapter_dir / "page_0001.jpg"
        image_path.write_bytes(b"fake-image")
        return {
            "download": {
                "output_dir": str(chapter_dir),
                "files": [str(image_path)],
            }
        }

    monkeypatch.setattr("mc_ws_dl_t.core.run_download", fake_run_download)

    result = download_selected_chapters_as_cbz(
        series_info=series,
        selected_chapters=[chapter],
        library_root_dir=tmp_path,
        config=ScraperConfig(),
        logger=_build_test_logger(),
    )

    series_root = Path(str(result["series_root"]))
    cbz_dir = series_root / "cbz"
    assert int(result["downloaded_count"]) == 1
    assert cbz_dir.exists() is True
    assert any(cbz_dir.glob("*.cbz"))
    assert (series_root / "chapters").exists() is False
