import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..config import ScraperConfig
from ..fetcher import build_session
from ..parser import ParsedPage, extract_image_urls, extract_title
from .common import extract_image_urls_by_selectors, unique_preserve_order


DOMAINS: tuple[str, ...] = ("m.mangatown.com", "mangatown.com")

CHAPTER_IMAGE_SELECTORS: tuple[str, ...] = (
    "div#viewer img",
    "div.page-content img",
    "div.manga_reading img",
    "div#image img",
    "article img",
)

CHAPTER_PATH_PATTERN = re.compile(r"/manga/[^/]+/c[0-9]+(?:\.[0-9]+)?(?:/.*)?$")
SERIES_PATH_PATTERN = re.compile(r"^/manga/[^/]+/?$")


@dataclass(frozen=True, slots=True)
class MangatownChapter:
    title: str
    url: str
    release: str = ""
    chapter_key: str = ""


def is_series_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(SERIES_PATH_PATTERN.match(parsed.path))


def is_chapter_url(url: str) -> bool:
    parsed = urlparse(url)
    return bool(CHAPTER_PATH_PATTERN.match(parsed.path))


def extract_series_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    title_node = soup.select_one("div.manga-detail-top div.title")
    if title_node:
        title = " ".join(title_node.get_text(" ", strip=True).split())
        if title:
            return title
    return extract_title(html)


def extract_series_cover_url(html: str, base_url: str | None = None) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    img = soup.select_one("div.manga-detail-top img.detail-cover, div.manga-detail-top img")
    if not img:
        return None

    raw_src = img.get("src") or img.get("data-src")
    if not raw_src:
        return None
    return urljoin(base_url, str(raw_src).strip()) if base_url else str(raw_src).strip()


def _extract_chapter_key(chapter_url: str) -> str:
    match = re.search(r"/c([0-9]+(?:\.[0-9]+)?)", chapter_url)
    return match.group(1) if match else ""


def _extract_series_slug(url: str) -> str:
    parsed = urlparse(url)
    match = re.search(r"^/manga/([^/]+)/", parsed.path, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _extract_chapter_prefix(url: str) -> str:
    parsed = urlparse(url)
    match = re.search(r"^(/manga/[^/]+/c[0-9]+(?:\.[0-9]+)?)", parsed.path, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _is_same_chapter(candidate_url: str, chapter_url: str | None) -> bool:
    if not chapter_url:
        return True

    expected_key = _extract_chapter_key(chapter_url)
    if expected_key and _extract_chapter_key(candidate_url) != expected_key:
        return False

    expected_series = _extract_series_slug(chapter_url)
    if expected_series and _extract_series_slug(candidate_url) != expected_series:
        return False

    expected_prefix = _extract_chapter_prefix(chapter_url)
    if expected_prefix:
        candidate_path = urlparse(candidate_url).path.lower()
        if not candidate_path.startswith(expected_prefix):
            return False

    return True


def parse_series_chapters(html: str, base_url: str | None = None) -> list[MangatownChapter]:
    # Mobile mangatown uses <ul class="detail-ch-list"> for chapter links.
    soup = BeautifulSoup(html, "lxml")
    chapter_links = soup.select("ul.detail-ch-list li a[href]")
    chapters: list[MangatownChapter] = []
    seen_urls: set[str] = set()

    for link in chapter_links:
        raw_href = str(link.get("href", "")).strip()
        if not raw_href:
            continue

        chapter_url = urljoin(base_url, raw_href) if base_url else raw_href
        if chapter_url in seen_urls:
            continue
        if not is_chapter_url(chapter_url):
            continue

        # Text is usually "C.xxx <date>" so we split for cleaner display.
        full_text = " ".join(link.get_text(" ", strip=True).split())
        if not full_text:
            full_text = f"Chapter {_extract_chapter_key(chapter_url)}"

        release = ""
        title = full_text
        title_match = re.match(r"^(C\.[^\s]+)\s+(.*)$", full_text)
        if title_match:
            title = title_match.group(1)
            release = title_match.group(2).strip()

        chapters.append(
            MangatownChapter(
                title=title,
                release=release,
                url=chapter_url,
                chapter_key=_extract_chapter_key(chapter_url),
            )
        )
        seen_urls.add(chapter_url)

    return chapters


def extract_chapter_page_urls(html: str, base_url: str | None = None) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    chapter_url = base_url
    page_urls: list[str] = []

    if chapter_url and is_chapter_url(chapter_url):
        page_urls.append(chapter_url)

    # Mangatown provides per-page navigation values in <option>.
    for option in soup.select("option[value]"):
        raw_value = str(option.get("value", "")).strip()
        if not raw_value or "/manga/" not in raw_value or "/c" not in raw_value:
            continue
        page_url = urljoin(chapter_url, raw_value) if chapter_url else raw_value
        if not is_chapter_url(page_url):
            continue
        if not _is_same_chapter(page_url, chapter_url):
            continue
        page_urls.append(page_url)

    # Also include pager links when present.
    for link in soup.select("#pager a[href], div#mangaread-page a[href]"):
        raw_href = str(link.get("href", "")).strip()
        if not raw_href or "/manga/" not in raw_href or "/c" not in raw_href:
            continue
        page_url = urljoin(chapter_url, raw_href) if chapter_url else raw_href
        if not is_chapter_url(page_url):
            continue
        if not _is_same_chapter(page_url, chapter_url):
            continue
        page_urls.append(page_url)

    return unique_preserve_order(page_urls)


def extract_page_image_url(html: str, base_url: str | None = None) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    image_node = soup.select_one("div#viewer img#image, div#viewer img[src], img#image")
    if not image_node:
        return None

    raw_src = (
        image_node.get("src")
        or image_node.get("data-src")
        or image_node.get("data-lazy-src")
        or image_node.get("data-original")
    )
    if not raw_src:
        return None

    src = str(raw_src).strip()
    if not src:
        return None
    return urljoin(base_url, src) if base_url else src


def fetch_chapter_image_urls(
    chapter_url: str,
    config: ScraperConfig,
    logger: logging.Logger | None = None,
) -> list[str]:
    # Mangatown mobile splits chapter pages into /1.html, /2.html, ... URLs.
    active_logger = logger or logging.getLogger("mc_ws_dl_t")
    session = build_session(config)
    try:
        try:
            response = session.get(chapter_url, timeout=config.timeout_seconds)
            response.raise_for_status()
            first_html = response.text
        except requests.RequestException as exc:
            active_logger.warning("Failed to fetch chapter landing page for full image scrape: %s", exc)
            return []

        # New Mangatown layout often includes all chapter pages as <img> tags in the
        # first chapter HTML response. Use those first when available.
        first_page_images = extract_image_urls_by_selectors(
            first_html,
            selectors=CHAPTER_IMAGE_SELECTORS,
            base_url=chapter_url,
            filter_content_only=True,
        )

        page_urls = extract_chapter_page_urls(first_html, base_url=chapter_url)
        if first_page_images and len(page_urls) <= 1:
            return unique_preserve_order(first_page_images)

        if not page_urls:
            # Keep a fallback to the requested chapter URL when no per-page links are exposed.
            page_urls = [chapter_url]

        image_urls: list[str] = []
        for page_url in page_urls:
            try:
                page_response = session.get(page_url, timeout=config.timeout_seconds)
                page_response.raise_for_status()
            except requests.RequestException as exc:
                active_logger.warning("Failed chapter page fetch: %s | %s", page_url, exc)
                continue

            # Some pages have a single viewer image, others return a full image list.
            page_image_urls = extract_image_urls_by_selectors(
                page_response.text,
                selectors=CHAPTER_IMAGE_SELECTORS,
                base_url=page_url,
                filter_content_only=True,
            )
            if page_image_urls:
                image_urls.extend(page_image_urls)
                continue

            image_url = extract_page_image_url(page_response.text, base_url=page_url)
            if image_url:
                image_urls.append(image_url)

        if image_urls:
            return unique_preserve_order(image_urls)
        return unique_preserve_order(first_page_images)
    finally:
        session.close()


def parse(html: str, base_url: str | None = None) -> ParsedPage:
    # Prioritize known reader containers to reduce page chrome and icon images.
    image_urls = extract_image_urls_by_selectors(
        html,
        selectors=CHAPTER_IMAGE_SELECTORS,
        base_url=base_url,
        filter_content_only=True,
    )

    # Fallback keeps this parser resilient while we refine selectors from real pages.
    if not image_urls:
        image_urls = extract_image_urls(html, base_url=base_url)

    # Chapter pages often keep a generic <title>, so prefer the in-page title block.
    soup = BeautifulSoup(html, "lxml")
    title_node = soup.select_one("div.title")
    parsed_title = ""
    if title_node:
        parsed_title = " ".join(title_node.get_text(" ", strip=True).split())
    if not parsed_title:
        parsed_title = extract_title(html)
    if " Page " in parsed_title and " / " in parsed_title:
        parsed_title = parsed_title.split(" Page ", 1)[0].strip()

    return ParsedPage(title=parsed_title, image_urls=image_urls)
