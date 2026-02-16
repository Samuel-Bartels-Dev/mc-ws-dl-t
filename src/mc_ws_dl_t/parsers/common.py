from urllib.parse import urljoin

from bs4 import BeautifulSoup


IMAGE_ATTRIBUTES: tuple[str, ...] = ("src", "data-src", "data-lazy-src", "data-original")


def _normalize_candidate(raw_value: object) -> str:
    # Some parsers return list-like values for attributes; normalize to one string.
    if isinstance(raw_value, list):
        if not raw_value:
            return ""
        return str(raw_value[0]).strip()
    return str(raw_value).strip()


def looks_like_content_image(url: str) -> bool:
    # Lightweight heuristic that filters likely UI assets for manga/webtoon pages.
    lowered = url.lower()
    blocked_tokens = ("logo", "avatar", "banner", "icon", "sprite", "loading", "thumb")
    if any(token in lowered for token in blocked_tokens):
        return False

    allowed_ext = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
    if any(lowered.endswith(ext) for ext in allowed_ext):
        return True

    # Keep URLs that may be signed or extension-less but still point to chapter images.
    return "chapter" in lowered or "page" in lowered or "manga" in lowered


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_image_urls_by_selectors(
    html: str,
    selectors: tuple[str, ...],
    base_url: str | None = None,
    filter_content_only: bool = False,
) -> list[str]:
    # Shared helper for site-specific parsers: select targeted image nodes and normalize URLs.
    soup = BeautifulSoup(html, "lxml")
    found_urls: list[str] = []

    for selector in selectors:
        for element in soup.select(selector):
            raw_candidate: object | None = None
            for attr_name in IMAGE_ATTRIBUTES:
                value = element.get(attr_name)
                if value:
                    raw_candidate = value
                    break

            if not raw_candidate:
                continue

            raw_url = _normalize_candidate(raw_candidate)
            if not raw_url:
                continue

            resolved_url = urljoin(base_url, raw_url) if base_url else raw_url
            if filter_content_only and not looks_like_content_image(resolved_url):
                continue

            found_urls.append(resolved_url)

    return unique_preserve_order(found_urls)
