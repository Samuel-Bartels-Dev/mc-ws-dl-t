from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


def _load_smoke_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "smoke_test_sites.py"
    spec = importlib.util.spec_from_file_location("smoke_test_sites", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_get_chapter_candidates_prefers_single_and_list() -> None:
    smoke = _load_smoke_module()
    config = {
        "chapter_url": "https://example.com/1",
        "chapter_urls": ["https://example.com/2", "https://example.com/3"],
    }
    assert smoke.get_chapter_candidates(config) == [
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    ]


def test_host_matches_site_handles_subdomains() -> None:
    smoke = _load_smoke_module()
    assert smoke.host_matches_site("https://m.mangatown.com/manga/x/c1/", ("mangatown.com",)) is True
    assert smoke.host_matches_site("https://example.com/x", ("mangatown.com",)) is False


def test_smoke_site_passes_with_fake_client() -> None:
    smoke = _load_smoke_module()

    class FakeClient:
        def get_text(self, url: str) -> tuple[str, str]:
            html = """
            <html>
              <head><title>Mangatown Chapter</title></head>
              <body>
                <div id="viewer"><img src="/images/page_001.jpg" /></div>
              </body>
            </html>
            """
            return html, url

    result = smoke.smoke_site(
        site_name="mangatown",
        domains=("m.mangatown.com", "mangatown.com"),
        site_config={"chapter_url": "https://m.mangatown.com/manga/demo/c1/"},
        client=FakeClient(),
        max_seconds_per_site=30,
    )

    assert result.ok is True
    assert result.image_count >= 1
