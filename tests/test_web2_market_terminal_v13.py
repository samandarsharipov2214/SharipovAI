from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_market_terminal_assets_connected() -> None:
    html = (ROOT / "dashboard/static/web2/index.html").read_text(encoding="utf-8")
    assert "market_terminal_v13.css" in html
    assert "market_terminal_v13.js" in html


def test_market_terminal_uses_only_verified_market_routes() -> None:
    js = (ROOT / "dashboard/static/web2/market_terminal_v13.js").read_text(encoding="utf-8")
    for route in (
        "/api/market/quote/",
        "/api/market/candles/",
        "/api/market/orderbook/",
        "/api/market/trades/",
    ):
        assert route in js
    assert "Math.random" not in js
    assert "synthetic" not in js.lower()
    assert "RSI 14" in js
    assert "SMA 7" in js
    assert "SMA 25" in js
    assert "Последние сделки" in js
    assert "Новости и решения ИИ" in js


def test_recent_trades_backend_is_verified_and_no_fallback() -> None:
    py = (ROOT / "dashboard/market_data_api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/market/trades/{symbol}")' in py
    assert 'f"{_BYBIT_MARKET_URL}/recent-trade"' in py
    assert '"verified": True' in py
    assert '"synthetic_fallback_used": False' in py
    assert "random" not in py.lower()
