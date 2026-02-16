from dataclasses import dataclass
from typing import Callable

from ..parser import ParsedPage


# Each parser plugin receives raw html + source URL context and returns normalized page data.
ParseFunc = Callable[[str, str | None], ParsedPage]


@dataclass(frozen=True, slots=True)
class ParserPlugin:
    # Friendly parser name used in logs, output payloads, and CLI selection.
    name: str
    # Domains this parser should handle automatically.
    domains: tuple[str, ...]
    # Parse implementation function for this plugin.
    parse: ParseFunc
