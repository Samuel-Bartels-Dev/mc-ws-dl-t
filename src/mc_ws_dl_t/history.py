import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HISTORY_FILE_NAME = ".mc_ws_dl_history.json"


def history_path_for_series(series_root: Path) -> Path:
    return series_root / HISTORY_FILE_NAME


def load_history(series_root: Path) -> dict[str, Any]:
    history_path = history_path_for_series(series_root)
    if not history_path.exists():
        return {"chapters": {}}

    try:
        loaded = json.loads(history_path.read_text(encoding="utf-8"))
    except Exception:
        return {"chapters": {}}

    if not isinstance(loaded, dict):
        return {"chapters": {}}
    if "chapters" not in loaded or not isinstance(loaded.get("chapters"), dict):
        loaded["chapters"] = {}
    return loaded


def save_history(series_root: Path, history: dict[str, Any]) -> Path:
    history_path = history_path_for_series(series_root)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    return history_path


def is_chapter_downloaded(history: dict[str, Any], chapter_url: str) -> bool:
    chapters = history.get("chapters")
    if not isinstance(chapters, dict):
        return False
    entry = chapters.get(chapter_url)
    return isinstance(entry, dict) and bool(entry.get("cbz_path"))


def mark_chapter_downloaded(
    history: dict[str, Any],
    chapter_url: str,
    chapter_title: str,
    cbz_path: Path,
    page_count: int,
) -> None:
    chapters = history.setdefault("chapters", {})
    if not isinstance(chapters, dict):
        history["chapters"] = {}
        chapters = history["chapters"]

    chapters[chapter_url] = {
        "title": chapter_title,
        "cbz_path": str(cbz_path),
        "page_count": page_count,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
