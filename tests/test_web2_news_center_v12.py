from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "dashboard/static/web2/index.html"
JS = ROOT / "dashboard/static/web2/news_center_v12.js"
CSS = ROOT / "dashboard/static/web2/news_center_v12.css"


def test_news_center_assets_are_connected():
    html = INDEX.read_text(encoding="utf-8")
    assert "news_center_v12.js?v=12" in html
    assert "news_center_v12.css?v=12" in html
    assert 'data-page="news"' in html


def test_news_center_uses_real_api_and_source_fields():
    source = JS.read_text(encoding="utf-8")
    assert "/api/social-news" in source
    assert "image_url" in source
    assert "source_url" in source
    assert "credibility" in source
    assert "related_assets" in source
    assert "Открыть источник" in source
    assert "Открыть на графике" in source


def test_news_center_has_no_demo_news_payload():
    source = JS.read_text(encoding="utf-8").lower()
    forbidden = ["math.random", "demo headline", "пример новости", "тестовая новость"]
    for marker in forbidden:
        assert marker not in source


def test_news_center_has_filters_and_mobile_styles():
    source = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert "verifiedNewsOnly" in source
    assert "importantNewsOnly" in source
    assert "newsSearch" in source
    assert "newsFilter" in source
    assert "@media(max-width:760px)" in css
