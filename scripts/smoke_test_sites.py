from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mc_ws_dl_t.parsers import mangatown  # noqa: E402
from mc_ws_dl_t.parsers import parse_for_url  # noqa: E402
from mc_ws_dl_t.parsers.registry import PARSER_PLUGINS  # noqa: E402


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class SiteResult:
    site: str
    ok: bool
    chapter_url: str
    image_count: int
    message: str
    elapsed_seconds: float


class SafeHttpClient:
    def __init__(
        self,
        timeout_seconds: int,
        retries: int,
        max_bytes: int,
        user_agent: str,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

        retry = Retry(
            total=retries,
            backoff_factor=0.4,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "HEAD"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def close(self) -> None:
        self.session.close()

    def get_text(self, url: str) -> tuple[str, str]:
        response = self.session.get(url, timeout=self.timeout_seconds, stream=True)
        response.raise_for_status()

        collected = bytearray()
        for chunk in response.iter_content(chunk_size=16 * 1024):
            if not chunk:
                continue
            collected.extend(chunk)
            if len(collected) > self.max_bytes:
                raise RuntimeError(
                    f"Response exceeded max-bytes guardrail ({self.max_bytes}) for URL: {url}"
                )
        response.close()

        text = collected.decode(response.encoding or "utf-8", errors="replace")
        return text, response.url


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    env_timeout = os.getenv("MC_WS_DL_T_SMOKE_TIMEOUT", "").strip()
    timeout_default = 20
    if env_timeout.isdigit():
        timeout_default = int(env_timeout)

    parser = argparse.ArgumentParser(
        description=(
            "Smoke-test all supported site adapters by fetching one chapter page and confirming "
            "at least one image URL is extracted."
        )
    )
    parser.add_argument(
        "--site",
        default="",
        help="Optional single site adapter name to test (e.g., mangatown).",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=Path("tests/smoke_urls.json"),
        help="Path to known-good sample URL config JSON.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=timeout_default,
        help="Per-request timeout for smoke HTTP fetches.",
    )
    parser.add_argument(
        "--max-seconds-per-site",
        type=int,
        default=60,
        help="Fail a site if smoke work exceeds this time budget.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Small retry count for transient network failures.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=2_500_000,
        help="Guardrail for maximum bytes to read per HTML response.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.8,
        help="Polite delay between site tests.",
    )
    return parser.parse_args(argv)


def load_smoke_urls(urls_file: Path) -> dict[str, dict[str, Any]]:
    if not urls_file.exists():
        raise RuntimeError(f"Smoke URL config was not found: {urls_file}")

    loaded = json.loads(urls_file.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise RuntimeError("Smoke URL config must be a JSON object keyed by site name.")

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in loaded.items():
        if not isinstance(value, dict):
            continue
        normalized[str(key).strip().lower()] = value
    return normalized


def host_matches_site(url: str, allowed_domains: tuple[str, ...]) -> bool:
    hostname = urlparse(url).netloc.lower()
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def get_chapter_candidates(site_config: dict[str, Any]) -> list[str]:
    chapter_urls: list[str] = []

    single_url = site_config.get("chapter_url")
    if isinstance(single_url, str) and single_url.strip():
        chapter_urls.append(single_url.strip())

    many_urls = site_config.get("chapter_urls")
    if isinstance(many_urls, list):
        for item in many_urls:
            if isinstance(item, str) and item.strip():
                chapter_urls.append(item.strip())

    return chapter_urls


def smoke_site(
    site_name: str,
    domains: tuple[str, ...],
    site_config: dict[str, Any],
    client: SafeHttpClient,
    max_seconds_per_site: int,
) -> SiteResult:
    start = time.perf_counter()
    chapter_candidates = get_chapter_candidates(site_config)

    # Mangatown supports real chapter-list parsing from series pages. We use this when available.
    series_url = site_config.get("series_url")
    if isinstance(series_url, str) and series_url.strip():
        series_html, series_final_url = client.get_text(series_url.strip())
        if site_name == "mangatown":
            chapters = mangatown.parse_series_chapters(series_html, base_url=series_final_url)
            if chapters:
                chapter_candidates.append(chapters[0].url)

    chapter_url = ""
    chapter_image_count = 0
    errors: list[str] = []

    # Try configured chapter URLs in order so we can keep a resilient fallback list in JSON.
    for candidate_url in chapter_candidates:
        if (time.perf_counter() - start) > max_seconds_per_site:
            return SiteResult(
                site=site_name,
                ok=False,
                chapter_url=candidate_url,
                image_count=0,
                message=f"Exceeded max-seconds-per-site={max_seconds_per_site}.",
                elapsed_seconds=time.perf_counter() - start,
            )

        try:
            chapter_html, chapter_final_url = client.get_text(candidate_url)
            if not host_matches_site(chapter_final_url, domains):
                raise RuntimeError(
                    f"Redirected to unexpected host '{urlparse(chapter_final_url).netloc}'."
                )

            parsed, parser_name = parse_for_url(
                chapter_html,
                url=chapter_final_url,
                force_parser=site_name,
            )
            if parser_name != site_name:
                raise RuntimeError(f"Unexpected parser selected: {parser_name}")
            if len(parsed.image_urls) < 1:
                raise RuntimeError("Parser returned zero image URLs.")

            chapter_url = chapter_final_url
            chapter_image_count = len(parsed.image_urls)
            return SiteResult(
                site=site_name,
                ok=True,
                chapter_url=chapter_url,
                image_count=chapter_image_count,
                message=f"Parsed '{parsed.title}' with {chapter_image_count} image URL(s).",
                elapsed_seconds=time.perf_counter() - start,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate_url} -> {exc}")

    if not chapter_candidates:
        errors.append("No chapter URLs were provided in smoke_urls.json for this site.")

    return SiteResult(
        site=site_name,
        ok=False,
        chapter_url=chapter_url,
        image_count=chapter_image_count,
        message=" | ".join(errors[:3]),
        elapsed_seconds=time.perf_counter() - start,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    smoke_urls = load_smoke_urls(args.urls_file)
    user_agent = os.getenv("MC_WS_DL_T_SMOKE_USER_AGENT", DEFAULT_USER_AGENT).strip() or DEFAULT_USER_AGENT

    supported_sites = [(plugin.name, plugin.domains) for plugin in PARSER_PLUGINS]
    if args.site:
        selected_name = args.site.strip().lower()
        supported_sites = [(name, domains) for name, domains in supported_sites if name == selected_name]
        if not supported_sites:
            print(f"[FAIL] Unknown site '{args.site}'. Known sites: {', '.join(plugin.name for plugin in PARSER_PLUGINS)}")
            return 2

    client = SafeHttpClient(
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
        max_bytes=args.max_bytes,
        user_agent=user_agent,
    )

    results: list[SiteResult] = []
    try:
        for index, (site_name, domains) in enumerate(supported_sites, start=1):
            site_config = smoke_urls.get(site_name, {})
            print(f"[INFO] ({index}/{len(supported_sites)}) Testing site '{site_name}'...")
            result = smoke_site(
                site_name=site_name,
                domains=domains,
                site_config=site_config,
                client=client,
                max_seconds_per_site=args.max_seconds_per_site,
            )
            results.append(result)
            status = "PASS" if result.ok else "FAIL"
            print(
                f"[{status}] {site_name} | images={result.image_count} | elapsed={result.elapsed_seconds:.1f}s | {result.message}"
            )
            if index < len(supported_sites):
                time.sleep(max(0.0, args.delay_seconds))
    finally:
        client.close()

    passed = [item for item in results if item.ok]
    failed = [item for item in results if not item.ok]
    print()
    print("Smoke Test Summary")
    print("------------------")
    print(f"Total: {len(results)} | Passed: {len(passed)} | Failed: {len(failed)}")
    for item in results:
        status = "PASS" if item.ok else "FAIL"
        chapter_fragment = f" | chapter={item.chapter_url}" if item.chapter_url else ""
        print(f"- {status} {item.site}{chapter_fragment}")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
