from mc_ws_dl_t.parser import extract_image_urls, extract_title, parse_page


def test_extract_title_prefers_html_title() -> None:
    # <title> should win over <h1> when both exist.
    html = "<html><head><title>My Manga Chapter</title></head><body><h1>Ignore me</h1></body></html>"
    assert extract_title(html) == "My Manga Chapter"


def test_extract_image_urls_resolves_relative_and_removes_duplicates() -> None:
    # Parser should resolve relative URLs and keep first-seen order without duplicates.
    html = """
    <html>
      <body>
        <img src="/img/001.jpg" />
        <img data-src="/img/002.jpg" />
        <img src="/img/001.jpg" />
      </body>
    </html>
    """
    urls = extract_image_urls(html, base_url="https://example.com/series/ch1")
    assert urls == [
        "https://example.com/img/001.jpg",
        "https://example.com/img/002.jpg",
    ]


def test_parse_page_collects_title_and_images() -> None:
    # End-to-end parser call should return title + URL list in one object.
    html = """
    <html>
      <head><title>Chapter 10</title></head>
      <body><img src="https://cdn.example.com/10-1.png" /></body>
    </html>
    """
    parsed = parse_page(html)
    assert parsed.title == "Chapter 10"
    assert parsed.image_urls == ["https://cdn.example.com/10-1.png"]
