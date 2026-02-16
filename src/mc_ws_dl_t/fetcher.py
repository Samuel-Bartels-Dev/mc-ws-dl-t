import logging
import time
from typing import Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import ScraperConfig


class FetchError(RuntimeError):
    # Single fetch exception type keeps error handling straightforward in CLI entrypoint.
    pass


def is_dynamic_site(url: str, dynamic_domains: Iterable[str]) -> bool:
    # Lightweight domain check to decide when JS rendering is likely required.
    lowered = url.lower()
    return any(domain.lower() in lowered for domain in dynamic_domains)


def build_session(config: ScraperConfig) -> requests.Session:
    # Centralized session setup gives every request the same user-agent and retry policy.
    session = requests.Session()
    session.headers.update({"User-Agent": config.user_agent})

    # Retry only safe methods by default to avoid accidental side effects.
    retry = Retry(
        total=config.retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_html_static(
    url: str,
    config: ScraperConfig,
    logger: logging.Logger | None = None,
    session: requests.Session | None = None,
) -> str:
    # This is the fast/default path for most pages.
    active_logger = logger or logging.getLogger("mc_ws_dl_t")
    active_logger.info("Static fetch: %s", url)

    # Allow an injected session for tests; otherwise manage our own session lifecycle.
    current_session = session or build_session(config)
    try:
        response = current_session.get(url, timeout=config.timeout_seconds)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        raise FetchError(f"Static fetch failed for '{url}': {exc}") from exc
    finally:
        # Only close session when we created it here.
        if session is None:
            current_session.close()


def fetch_html_dynamic(
    url: str,
    config: ScraperConfig,
    browser: str = "chrome",
    logger: logging.Logger | None = None,
) -> str:
    # Dynamic path is slower but useful for JS-heavy sites.
    active_logger = logger or logging.getLogger("mc_ws_dl_t")
    active_logger.info("Dynamic fetch: %s (browser=%s)", url, browser)

    try:
        from selenium import webdriver  # type: ignore[import-not-found]
        from selenium.common.exceptions import WebDriverException  # type: ignore[import-not-found]
        from selenium.webdriver.chrome.options import Options as ChromeOptions  # type: ignore[import-not-found]
        from selenium.webdriver.firefox.options import Options as FirefoxOptions  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FetchError(
            "Dynamic fetch requires selenium. Install optional deps with: pip install -e .[dynamic]"
        ) from exc

    driver = None
    try:
        browser_name = browser.lower().strip()
        if browser_name == "chrome":
            # Chrome args chosen for stable headless runs in CI and local Windows environments.
            options = ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--disable-gpu")
            options.add_argument("--no-sandbox")
            driver = webdriver.Chrome(options=options)
        elif browser_name == "firefox":
            # Firefox path kept for teams standardizing on geckodriver.
            options = FirefoxOptions()
            options.add_argument("--headless")
            driver = webdriver.Firefox(options=options)
        else:
            raise FetchError(f"Unsupported browser '{browser}'. Use 'chrome' or 'firefox'.")

        driver.set_page_load_timeout(config.timeout_seconds)
        driver.get(url)
        # Fixed wait keeps behavior predictable; upgrade to explicit waits later if needed.
        time.sleep(config.wait_seconds)
        return driver.page_source
    except WebDriverException as exc:
        raise FetchError(f"Dynamic fetch failed for '{url}': {exc}") from exc
    finally:
        # Always release browser process if one was started.
        if driver:
            driver.quit()


def fetch_page(
    url: str,
    config: ScraperConfig,
    logger: logging.Logger | None = None,
    prefer_dynamic: bool = False,
    browser: str = "chrome",
) -> str:
    # This orchestrator controls fallback order and keeps strategy logic in one place.
    active_logger = logger or logging.getLogger("mc_ws_dl_t")
    should_try_dynamic_first = prefer_dynamic or is_dynamic_site(url, config.dynamic_domains)

    if should_try_dynamic_first:
        try:
            return fetch_html_dynamic(url, config, browser=browser, logger=active_logger)
        except FetchError as exc:
            # Dynamic fail does not end run immediately; static often still succeeds.
            active_logger.warning("Dynamic fetch failed first pass: %s", exc)

    try:
        return fetch_html_static(url, config, logger=active_logger)
    except FetchError as exc:
        # One warning here gives context before final fallback attempt.
        active_logger.warning("Static fetch failed: %s", exc)

    # Last attempt before bubbling failure to caller.
    active_logger.info("Trying dynamic fallback after static failure.")
    return fetch_html_dynamic(url, config, browser=browser, logger=active_logger)
