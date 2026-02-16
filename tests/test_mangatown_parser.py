from mc_ws_dl_t.parsers import mangatown


def test_mangatown_url_classification() -> None:
    assert mangatown.is_series_url("https://m.mangatown.com/manga/tales_of_demons_and_gods") is True
    assert mangatown.is_chapter_url("https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/") is True
    assert mangatown.is_chapter_url("https://m.mangatown.com/manga/tales_of_demons_and_gods/") is False


def test_parse_series_chapters_extracts_entries() -> None:
    html = """
    <html>
      <body>
        <div class="manga-detail-top"><div class="title">Tales of Demons and Gods</div></div>
        <ul class="detail-ch-list">
          <li><a href="/manga/tales_of_demons_and_gods/c512.5/">C.512.5 Feb 12,2026</a></li>
          <li><a href="/manga/tales_of_demons_and_gods/c512/">C.512 Feb 05,2026</a></li>
        </ul>
      </body>
    </html>
    """
    chapters = mangatown.parse_series_chapters(
        html,
        base_url="https://m.mangatown.com/manga/tales_of_demons_and_gods",
    )
    assert len(chapters) == 2
    assert chapters[0].title == "C.512.5"
    assert chapters[0].release == "Feb 12,2026"
    assert chapters[0].url == "https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/"
    assert chapters[0].chapter_key == "512.5"


def test_extract_chapter_page_urls() -> None:
    html = """
    <html>
      <body>
        <select>
          <option value="/manga/tales_of_demons_and_gods/c512.5/">1</option>
          <option value="/manga/tales_of_demons_and_gods/c512.5/2.html">2</option>
          <option value="/manga/tales_of_demons_and_gods/c512.5/3.html">3</option>
        </select>
        <div id="pager">
          <a href="/manga/tales_of_demons_and_gods/c512.5/2.html">Next</a>
        </div>
      </body>
    </html>
    """
    page_urls = mangatown.extract_chapter_page_urls(
        html,
        base_url="https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/",
    )
    assert page_urls == [
        "https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/",
        "https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/2.html",
        "https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/3.html",
    ]


def test_extract_page_image_url() -> None:
    html = """
    <html>
      <body>
        <div id="viewer">
          <img id="image" src="//zjcdn.mangahere.org/store/manga/18607/512.5/compressed/bp_001.jpg" />
        </div>
      </body>
    </html>
    """
    image_url = mangatown.extract_page_image_url(
        html,
        base_url="https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/",
    )
    assert image_url == "https://zjcdn.mangahere.org/store/manga/18607/512.5/compressed/bp_001.jpg"


def test_parse_prefers_inline_title_block() -> None:
    html = """
    <html>
      <head><title>MangaTown Mobile</title></head>
      <body>
        <div class="title">Tales of Demons and Gods 512.5 Page 1 / Tales of Demons and Gods Manga</div>
        <div id="viewer"><img id="image" src="/img/page_001.jpg" /></div>
      </body>
    </html>
    """
    parsed = mangatown.parse(html, base_url="https://m.mangatown.com/manga/tales_of_demons_and_gods/c512.5/")
    assert parsed.title == "Tales of Demons and Gods 512.5"
