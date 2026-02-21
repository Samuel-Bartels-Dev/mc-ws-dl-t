from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from urllib.parse import urlparse


CHAPTER_NUMBER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")


def parse_positive_int(raw_value: str, field_name: str) -> int:
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return value


def parse_non_negative_int(raw_value: str, field_name: str) -> int:
    try:
        value = int(raw_value.strip())
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return value


def validate_http_url(raw_url: str, field_name: str = "URL") -> str:
    normalized = raw_url.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must start with http:// or https:// and include a hostname.")
    return normalized


def normalize_output_file(raw_path: str) -> Path | None:
    normalized = raw_path.strip()
    if not normalized:
        return None
    return Path(normalized).expanduser()


def normalize_directory(raw_path: str, field_name: str) -> Path:
    normalized = raw_path.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required.")

    directory = Path(normalized).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def parse_optional_chapter_range(start_raw: str, end_raw: str) -> tuple[Decimal | None, Decimal | None]:
    start_text = start_raw.strip()
    end_text = end_raw.strip()

    if not start_text and not end_text:
        return None, None

    start_value = _parse_decimal(start_text, "Range start") if start_text else None
    end_value = _parse_decimal(end_text, "Range end") if end_text else None

    if start_value is not None and end_value is not None and start_value > end_value:
        raise ValueError("Range start cannot be greater than range end.")

    return start_value, end_value


def extract_chapter_number(chapter_key: str, chapter_title: str) -> Decimal | None:
    if chapter_key.strip():
        parsed_key = _try_parse_decimal(chapter_key)
        if parsed_key is not None:
            return parsed_key

    key_match = CHAPTER_NUMBER_PATTERN.search(chapter_title)
    if not key_match:
        return None
    return _try_parse_decimal(key_match.group(1))


def _parse_decimal(raw_value: str, field_name: str) -> Decimal:
    parsed = _try_parse_decimal(raw_value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a chapter number like 12 or 12.5.")
    return parsed


def _try_parse_decimal(raw_value: str) -> Decimal | None:
    candidate = raw_value.strip()
    if not candidate:
        return None
    try:
        return Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None

