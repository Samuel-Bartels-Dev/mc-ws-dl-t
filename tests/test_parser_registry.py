from mc_ws_dl_t.parsers.registry import parse_for_url, resolve_parser_for_url


def test_resolve_parser_for_known_domain() -> None:
    parser_plugin = resolve_parser_for_url("https://manganato.com/manga-abcd/chapter-1")
    assert parser_plugin is not None
    assert parser_plugin.name == "manganato"


def test_resolve_parser_for_mangatown_mobile_domain() -> None:
    parser_plugin = resolve_parser_for_url("https://m.mangatown.com/manga/my-series/c001")
    assert parser_plugin is not None
    assert parser_plugin.name == "mangatown"


def test_resolve_parser_for_webtoons_domain() -> None:
    parser_plugin = resolve_parser_for_url("https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95")
    assert parser_plugin is not None
    assert parser_plugin.name == "webtoons"


def test_parse_for_url_uses_generic_for_unknown_domain() -> None:
    html = """
    <html>
      <head><title>Unknown Site Chapter</title></head>
      <body>
        <img src="/images/001.jpg" />
      </body>
    </html>
    """
    parsed, parser_name = parse_for_url(html, url="https://example.com/ch1")
    assert parser_name == "generic"
    assert parsed.title == "Unknown Site Chapter"
    assert parsed.image_urls == ["https://example.com/images/001.jpg"]


def test_parse_for_url_auto_uses_site_plugin() -> None:
    html = """
    <html>
      <head><title>Chapter 1</title></head>
      <body>
        <img src="/assets/logo.png" />
        <div class="container-chapter-reader">
          <img src="/images/page-001.jpg" />
          <img src="/images/page-002.jpg" />
        </div>
      </body>
    </html>
    """
    parsed, parser_name = parse_for_url(html, url="https://manganato.com/manga-xyz/chapter-1")
    assert parser_name == "manganato"
    assert parsed.image_urls == [
        "https://manganato.com/images/page-001.jpg",
        "https://manganato.com/images/page-002.jpg",
    ]


def test_parse_for_url_force_parser_works() -> None:
    html = """
    <html>
      <head><title>Forced Parser</title></head>
      <body>
        <div id="_imageList">
          <img src="/chapter/1.webp" />
        </div>
      </body>
    </html>
    """
    parsed, parser_name = parse_for_url(
        html,
        url="https://example.com/not-webtoons",
        force_parser="webtoons",
    )
    assert parser_name == "webtoons"
    assert parsed.image_urls == ["https://example.com/chapter/1.webp"]


def test_parse_for_url_auto_uses_mangatown_plugin() -> None:
    html = """
    <html>
      <head><title>Mangatown Chapter</title></head>
      <body>
        <div id="viewer">
          <img src="/chapter/p001.jpg" />
          <img src="/chapter/p002.jpg" />
        </div>
      </body>
    </html>
    """
    parsed, parser_name = parse_for_url(html, url="https://m.mangatown.com/manga/abc/chapter_1")
    assert parser_name == "mangatown"
    assert parsed.image_urls == [
        "https://m.mangatown.com/chapter/p001.jpg",
        "https://m.mangatown.com/chapter/p002.jpg",
    ]
