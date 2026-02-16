from mc_ws_dl_t.config import ScraperConfig
from mc_ws_dl_t.fetcher import is_dynamic_site


def test_is_dynamic_site_matches_known_domain() -> None:
    # Known manga domain should trigger dynamic-first behavior.
    config = ScraperConfig()
    assert is_dynamic_site("https://manganato.com/manga-abc", config.dynamic_domains) is True


def test_is_dynamic_site_false_for_unknown_domain() -> None:
    # Generic site should stay on fast static path by default.
    config = ScraperConfig()
    assert is_dynamic_site("https://example.com/chapter-1", config.dynamic_domains) is False


def test_is_dynamic_site_false_for_mangatown_by_default() -> None:
    # Mangatown pages are handled with static parsing to avoid unnecessary Selenium launches.
    config = ScraperConfig()
    assert is_dynamic_site("https://m.mangatown.com/manga/tower_of_god", config.dynamic_domains) is False
