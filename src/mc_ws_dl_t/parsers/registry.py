from urllib.parse import urlparse

from ..parser import ParsedPage, parse_page
from .base import ParserPlugin
from .mangadex import DOMAINS as MANGADEX_DOMAINS
from .mangadex import parse as parse_mangadex
from .manganato import DOMAINS as MANGANATO_DOMAINS
from .manganato import parse as parse_manganato
from .mangatown import DOMAINS as MANGATOWN_DOMAINS
from .mangatown import parse as parse_mangatown
from .webtoons import DOMAINS as WEBTOONS_DOMAINS
from .webtoons import parse as parse_webtoons


PARSER_PLUGINS: tuple[ParserPlugin, ...] = (
    ParserPlugin(name="manganato", domains=MANGANATO_DOMAINS, parse=parse_manganato),
    ParserPlugin(name="mangadex", domains=MANGADEX_DOMAINS, parse=parse_mangadex),
    ParserPlugin(name="mangatown", domains=MANGATOWN_DOMAINS, parse=parse_mangatown),
    ParserPlugin(name="webtoons", domains=WEBTOONS_DOMAINS, parse=parse_webtoons),
)


def get_available_parser_names() -> list[str]:
    # Include "auto" and "generic" to cover dispatcher and fallback modes.
    plugin_names = [plugin.name for plugin in PARSER_PLUGINS]
    return ["auto", "generic", *plugin_names]


def _get_hostname(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower()


def resolve_parser_for_url(url: str) -> ParserPlugin | None:
    # Match plugin when hostname equals domain or subdomain of domain.
    hostname = _get_hostname(url)
    if not hostname:
        return None

    for plugin in PARSER_PLUGINS:
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in plugin.domains):
            return plugin

    return None


def resolve_parser_by_name(name: str) -> ParserPlugin | None:
    lowered = name.lower().strip()
    for plugin in PARSER_PLUGINS:
        if plugin.name == lowered:
            return plugin
    return None


def parse_for_url(
    html: str,
    url: str | None = None,
    force_parser: str = "auto",
) -> tuple[ParsedPage, str]:
    # Force parser path is useful when testing or handling new domains with known HTML structure.
    normalized_force = force_parser.lower().strip()
    if normalized_force == "generic":
        return parse_page(html, base_url=url), "generic"

    if normalized_force != "auto":
        forced_plugin = resolve_parser_by_name(normalized_force)
        if not forced_plugin:
            valid_names = ", ".join(get_available_parser_names())
            raise ValueError(f"Unknown parser '{force_parser}'. Valid options: {valid_names}")
        return forced_plugin.parse(html, url), forced_plugin.name

    if url:
        matched_plugin = resolve_parser_for_url(url)
        if matched_plugin:
            return matched_plugin.parse(html, url), matched_plugin.name

    return parse_page(html, base_url=url), "generic"
