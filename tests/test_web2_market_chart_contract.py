from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_api_has_verified_candles_and_orderbook() -> None:
    text = (ROOT / "dashboard" / "market_data_api.py").read_text(encoding="utf-8")
    assert '/api/market/candles/{symbol}' in text
    assert '/api/market/orderbook/{symbol}' in text
    assert 'synthetic_fallback_used' in text
    assert 'https://api.bybit.com/v5/market' in text


def test_web2_uses_real_candlestick_chart() -> None:
    text = (ROOT / "dashboard" / "static" / "web2" / "web2.js").read_text(encoding="utf-8")
    assert '/api/market/candles/' in text
    assert '/api/market/quote/' in text
    assert '/api/market/orderbook/' in text
    assert 'candleChart' in text
    assert 'drawCandleCanvas' in text
    assert "Math.random" not in text


def test_russian_is_default_and_three_languages_exist() -> None:
    html = (ROOT / "dashboard" / "static" / "web2" / "index.html").read_text(encoding="utf-8")
    assert '<html lang="ru">' in html
    assert 'Решение ИИ' in html
    assert 'Центр рисков' in html
    assert 'Центр обучения' in html
    assert 'Хранилище доказательств' in html
    assert 'data-lang="ru"' in html
    assert 'data-lang="en"' in html
    assert 'data-lang="uz"' in html
