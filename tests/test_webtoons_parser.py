from mc_ws_dl_t.parsers import webtoons


def test_webtoons_url_classification() -> None:
    assert (
        webtoons.is_series_url(
            "https://www.webtoons.com/en/fantasy/the-patron-of-villains/list?title_no=9321"
        )
        is True
    )
    assert (
        webtoons.is_chapter_url(
            "https://www.webtoons.com/en/fantasy/the-patron-of-villains/episode-9/viewer?title_no=9321&episode_no=9"
        )
        is True
    )
    assert (
        webtoons.is_chapter_url("https://www.webtoons.com/en/fantasy/the-patron-of-villains/list?title_no=9321")
        is False
    )


def test_parse_series_chapters_extracts_webtoons_entries() -> None:
    html = """
    <html>
      <body>
        <div class="detail_header">
          <h1 class="subj">The Patron of Villains</h1>
        </div>
        <ul id="_listUl">
          <li>
            <a href="/en/fantasy/the-patron-of-villains/episode-9/viewer?title_no=9321&episode_no=9">
              <span class="subj">Episode 9</span>
              <span class="date">Feb 19, 2026</span>
            </a>
          </li>
          <li>
            <a href="/en/fantasy/the-patron-of-villains/episode-8/viewer?title_no=9321&episode_no=8">
              <span class="subj">Episode 8</span>
              <span class="date">Feb 12, 2026</span>
            </a>
          </li>
        </ul>
      </body>
    </html>
    """
    chapters = webtoons.parse_series_chapters(
        html,
        base_url="https://www.webtoons.com/en/fantasy/the-patron-of-villains/list?title_no=9321",
    )
    assert len(chapters) == 2
    assert chapters[0].title == "Episode 9"
    assert chapters[0].release == "Feb 19, 2026"
    assert chapters[0].chapter_key == "9"
    assert (
        chapters[0].url
        == "https://www.webtoons.com/en/fantasy/the-patron-of-villains/episode-9/viewer?title_no=9321&episode_no=9"
    )


def test_parse_uses_data_url_images_and_skips_transparency_placeholder() -> None:
    html = """
    <html>
      <head><title>Episode 9 | The Patron of Villains</title></head>
      <body>
        <div id="_imageList">
          <img src="https://webtoons-static.pstatic.net/image/bg_transparency.png"
               data-url="https://webtoon-phinf.pstatic.net/a/page_0001.jpg?type=q90" />
          <img src="https://webtoons-static.pstatic.net/image/bg_transparency.png"
               data-url="https://webtoon-phinf.pstatic.net/a/page_0002.jpg?type=q90" />
        </div>
      </body>
    </html>
    """
    parsed = webtoons.parse(
        html,
        base_url="https://www.webtoons.com/en/fantasy/the-patron-of-villains/episode-9/viewer?title_no=9321&episode_no=9",
    )
    assert parsed.title == "Episode 9 | The Patron of Villains"
    assert parsed.image_urls == [
        "https://webtoon-phinf.pstatic.net/a/page_0001.jpg?type=q90",
        "https://webtoon-phinf.pstatic.net/a/page_0002.jpg?type=q90",
    ]

