from ..parser import ParsedPage, extract_image_urls, extract_title
from .common import extract_image_urls_by_selectors


DOMAINS: tuple[str, ...] = ("mangadex.org",)

CHAPTER_IMAGE_SELECTORS: tuple[str, ...] = (
    "div.md--reader-chapter img",
    "div.reader--image img",
    "div.chapter-container img",
)


def parse(html: str, base_url: str | None = None) -> ParsedPage:
    # Prefer reader-specific blocks so we capture manga pages, not navigation graphics.
    image_urls = extract_image_urls_by_selectors(
        html,
        selectors=CHAPTER_IMAGE_SELECTORS,
        base_url=base_url,
        filter_content_only=True,
    )

    if not image_urls:
        image_urls = extract_image_urls(html, base_url=base_url)

    return ParsedPage(title=extract_title(html), image_urls=image_urls)
