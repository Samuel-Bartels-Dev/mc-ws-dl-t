import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from ..config import ScraperConfig
from ..fetcher import build_session
from ..parser import ParsedPage, extract_image_urls, extract_title
from .common import unique_preserve_order


DOMAINS: tuple[str, ...] = ("webtoons.com",)

CHAPTER_IMAGE_SELECTORS: tuple[str, ...] = (
    "#_imageList img",
    "div#_imageList img",
    "div.viewer_lst img",
)


@dataclass(frozen=True, slots=True)
class WebtoonsChapter:
    title: str
    url: str
    release: str = ""
    chapter_key: str = ""


def _get_query_value(url: str, key: str) -> str:
    query_values = parse_qs(urlparse(url).query).get(key)
    if not query_values:
        return ""
    return str(query_values[0]).strip()


def _extract_episode_no(chapter_url: str) -> str:
    episode_no = _get_query_value(chapter_url, "episode_no")
    if episode_no:
        return episode_no

    match = re.search(r"/episode[-_](\d+)", urlparse(chapter_url).path, re.IGNORECASE)
    return match.group(1) if match else ""


def _clean_webtoons_title(raw_title: str) -> str:
    title = raw_title.strip()
    if not title:
        return title
    if title.lower().endswith("| webtoon"):
        return title.rsplit("|", 1)[0].strip()
    return title


def is_series_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path.lower().endswith("/list") and bool(_get_query_value(url, "title_no"))


def is_chapter_url(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.path.lower().endswith("/viewer"):
        return False
    return bool(_get_query_value(url, "title_no") and _extract_episode_no(url))


def extract_series_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    title_node = soup.select_one("div.detail_header h1.subj, h1.subj")
    if title_node:
        title = " ".join(title_node.get_text(" ", strip=True).split())
        if title:
            return title
    return _clean_webtoons_title(extract_title(html))


def extract_series_cover_url(html: str, base_url: str | None = None) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    image_node = soup.select_one("div.detail_header span.thmb img, div.detail_header img, span.thmb img")
    if image_node:
        raw_src = (
            image_node.get("data-url")
            or image_node.get("data-src")
            or image_node.get("data-original")
            or image_node.get("src")
        )
        if raw_src:
            src = str(raw_src).strip()
            if src:
                return urljoin(base_url, src) if base_url else src

    og_image = soup.select_one("meta[property='og:image']")
    if og_image:
        content = str(og_image.get("content", "")).strip()
        if content:
            return content

    return None


def parse_series_chapters(html: str, base_url: str | None = None) -> list[WebtoonsChapter]:
    soup = BeautifulSoup(html, "lxml")
    chapter_rows = soup.select("#_listUl li")
    chapters: list[WebtoonsChapter] = []
    seen_urls: set[str] = set()

    for row in chapter_rows:
        link_node = row.select_one("a[href]")
        if not link_node:
            continue

        raw_href = str(link_node.get("href", "")).strip()
        if not raw_href:
            continue
        chapter_url = urljoin(base_url, raw_href) if base_url else raw_href
        if not is_chapter_url(chapter_url):
            continue
        if chapter_url in seen_urls:
            continue

        title_node = row.select_one("span.subj, p.subj")
        title_text = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else ""
        chapter_key = _extract_episode_no(chapter_url)
        if not title_text:
            title_text = f"Episode {chapter_key}" if chapter_key else "Episode"

        date_node = row.select_one("span.date")
        release_text = " ".join(date_node.get_text(" ", strip=True).split()) if date_node else ""

        chapters.append(
            WebtoonsChapter(
                title=title_text,
                url=chapter_url,
                release=release_text,
                chapter_key=chapter_key,
            )
        )
        seen_urls.add(chapter_url)

    return chapters


def _build_series_page_url(series_url: str, page: int) -> str:
    parsed = urlparse(series_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page)]
    encoded_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, encoded_query, parsed.fragment)
    )


def _has_next_series_page(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    next_link = soup.select_one("div.paginate a.pg_next[href]")
    if not next_link:
        return False
    raw_href = str(next_link.get("href", "")).strip()
    return bool(raw_href and raw_href != "#")


def fetch_series_chapters(
    series_url: str,
    config: ScraperConfig,
    logger: logging.Logger | None = None,
    first_html: str | None = None,
    max_pages: int = 300,
) -> list[WebtoonsChapter]:
    # Fetch all list pages sequentially so queues can include the full series.
    active_logger = logger or logging.getLogger("mc_ws_dl_t")
    collected: list[WebtoonsChapter] = []
    seen_chapter_urls: set[str] = set()

    def collect_from_page(page_html: str, page_url: str) -> None:
        for chapter in parse_series_chapters(page_html, base_url=page_url):
            if chapter.url in seen_chapter_urls:
                continue
            seen_chapter_urls.add(chapter.url)
            collected.append(chapter)

    session = build_session(config)
    try:
        current_html = first_html
        if current_html is None:
            try:
                response = session.get(series_url, timeout=config.timeout_seconds)
                response.raise_for_status()
                current_html = response.text
                collect_from_page(current_html, response.url or series_url)
            except requests.RequestException as exc:
                active_logger.warning("Failed to fetch Webtoons series page: %s", exc)
                return []
        else:
            collect_from_page(current_html, series_url)

        if not _has_next_series_page(current_html):
            return collected

        for page_number in range(2, max_pages + 1):
            page_url = _build_series_page_url(series_url, page_number)
            try:
                response = session.get(page_url, timeout=config.timeout_seconds)
                response.raise_for_status()
            except requests.RequestException as exc:
                active_logger.warning("Failed Webtoons list page fetch: %s | %s", page_url, exc)
                break

            page_html = response.text
            before_count = len(collected)
            collect_from_page(page_html, response.url or page_url)
            has_next = _has_next_series_page(page_html)
            if not has_next:
                break
            if len(collected) == before_count:
                # Defensive stop in case paging loops on an unexpected response.
                break

        return collected
    finally:
        session.close()


def parse(html: str, base_url: str | None = None) -> ParsedPage:
    # Webtoons chapter images are usually stored in data-url while src is a placeholder.
    soup = BeautifulSoup(html, "lxml")
    image_urls: list[str] = []

    for selector in CHAPTER_IMAGE_SELECTORS:
        for image_node in soup.select(selector):
            raw_candidate = (
                image_node.get("data-url")
                or image_node.get("data-src")
                or image_node.get("data-lazy-src")
                or image_node.get("data-original")
                or image_node.get("src")
            )
            if not raw_candidate:
                continue
            raw_url = str(raw_candidate).strip()
            if not raw_url:
                continue
            resolved_url = urljoin(base_url, raw_url) if base_url else raw_url
            lowered = resolved_url.lower()
            if "bg_transparency.png" in lowered:
                continue
            image_urls.append(resolved_url)

    image_urls = unique_preserve_order(image_urls)
    if not image_urls:
        image_urls = [
            image_url
            for image_url in extract_image_urls(html, base_url=base_url)
            if "bg_transparency.png" not in image_url.lower()
        ]

    return ParsedPage(
        title=_clean_webtoons_title(extract_title(html)),
        image_urls=image_urls,
    )
