from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_market_api_has_verified_candles_and_orderbook() -> None:
    text = (ROOT / "dashboard" / "market_data_api.py").read_text(encoding="utf-8")
    assert "/api/market/candles/{symbol}" in text
    assert "/api/market/orderbook/{symbol}" in text
    assert "synthetic_fallback_used" in text
    assert "https://api.bybit.com/v5/market" in text


def test_web2_uses_tradingview_chart_with_verified_project_evidence() -> None:
    terminal = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    intelligence = (WEB2 / "market_intelligence_v33.js").read_text(encoding="utf-8")
    assert "embed-widget-advanced-chart.js" in terminal
    assert "/api/market/bybit-websocket/quote/" in terminal
    assert "/api/market/orderbook/" in terminal
    assert "/api/market/trades/" in terminal
    assert "/api/market-intelligence/replay" in intelligence
    assert "Math.random" not in terminal
    assert "Math.random" not in intelligence


def test_russian_is_default_three_languages_exist_and_theme_is_declared() -> None:
    html = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert '<html lang="ru"' in html
    assert 'data-theme="dark"' in html
    assert "Решение ИИ" in html
    assert "Центр рисков" in html
    assert "Центр обучения" in html
    assert "Хранилище доказательств" in html
    assert 'data-lang="ru"' in html
    assert 'data-lang="en"' in html
    assert 'data-lang="uz"' in html
