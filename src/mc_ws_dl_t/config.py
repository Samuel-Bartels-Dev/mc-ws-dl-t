from dataclasses import dataclass, field
from typing import Sequence


# Known domains that commonly require dynamic/JS rendering.
DEFAULT_DYNAMIC_DOMAINS: tuple[str, ...] = (
    "mangakakalot.com",
    "manganato.com",
    "m.mangatown.com",
    "mangatown.com",
    "webtoons.com",
    "mangadex.org",
)


@dataclass(slots=True)
class ScraperConfig:
    # Request timeout for static HTTP and dynamic page loads.
    timeout_seconds: int = 15
    # Extra wait for JS-rendered content in dynamic mode.
    wait_seconds: int = 5
    # Retry count for transient HTTP failures.
    retries: int = 3
    # Browser-like user-agent to reduce bot-block false positives on basic sites.
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    # Domains where dynamic mode is usually worth trying first.
    dynamic_domains: Sequence[str] = field(default_factory=lambda: DEFAULT_DYNAMIC_DOMAINS)
