from ..parser import ParsedPage, extract_image_urls, extract_title
from .common import extract_image_urls_by_selectors


# Manganato and Mangakakalot share similar chapter page structure.
DOMAINS: tuple[str, ...] = ("manganato.com", "mangakakalot.com")

CHAPTER_IMAGE_SELECTORS: tuple[str, ...] = (
    "div.container-chapter-reader img",
    "div.chapter-content img",
    "div.reading-content img",
)


def parse(html: str, base_url: str | None = None) -> ParsedPage:
    # Use chapter container selectors first to avoid header/footer image noise.
    image_urls = extract_image_urls_by_selectors(
        html,
        selectors=CHAPTER_IMAGE_SELECTORS,
        base_url=base_url,
        filter_content_only=True,
    )

    # Fallback keeps parser resilient if the site changes class names.
    if not image_urls:
        image_urls = extract_image_urls(html, base_url=base_url)

    return ParsedPage(title=extract_title(html), image_urls=image_urls)
