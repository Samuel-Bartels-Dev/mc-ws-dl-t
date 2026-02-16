from dataclasses import asdict, dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Generic parser utilities live here and are used as fallback when no site plugin matches.

@dataclass(slots=True)
class ParsedPage:
    title: str
    image_urls: list[str]

    def to_dict(self) -> dict[str, object]:
        # Simple conversion helper used when serializing CLI output payload.
        return asdict(self)


def extract_title(html: str) -> str:
    # Title priority: <title> first, then <h1>, then fallback token.
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.text.strip():
        return soup.title.text.strip()

    h1 = soup.find("h1")
    if h1 and h1.text.strip():
        return h1.text.strip()

    return "untitled-page"


def extract_image_urls(html: str, base_url: str | None = None) -> list[str]:
    # Collect image references across common lazy-load attributes.
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    result: list[str] = []

    for img in soup.find_all("img"):
        raw_url_candidate = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )
        if not raw_url_candidate:
            continue

        # Some parsers can return list-like values for attributes; normalize to single string.
        if isinstance(raw_url_candidate, list):
            if not raw_url_candidate:
                continue
            raw_url = str(raw_url_candidate[0]).strip()
        else:
            raw_url = str(raw_url_candidate).strip()

        if not raw_url:
            continue

        # Resolve relative paths when caller supplies the source page URL.
        resolved = urljoin(base_url, raw_url) if base_url else raw_url
        if resolved in seen:
            continue

        # Preserve original order while preventing duplicates.
        seen.add(resolved)
        result.append(resolved)

    return result


def parse_page(html: str, base_url: str | None = None) -> ParsedPage:
    # Parser entrypoint keeps title and image extraction together for downstream use.
    return ParsedPage(
        title=extract_title(html),
        image_urls=extract_image_urls(html, base_url=base_url),
    )
