from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard/static/web2"


def test_current_market_terminal_assets_are_connected() -> None:
    html = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "tradingview_market_v32.css?" in html
    assert "tradingview_market_v32.js?" in html
    assert "market_intelligence_v33.css?" in html
    assert "market_intelligence_v33.js?" in html
    assert "market_terminal_v13.css" not in html
    assert "market_terminal_v13.js" not in html


def test_tradingview_terminal_uses_verified_market_routes() -> None:
    js = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    for route in (
        "/api/market/bybit-websocket/quote/",
        "/api/market/orderbook/",
        "/api/market/trades/",
        "/api/virtual-account/state",
    ):
        assert route in js
    for widget in (
        "embed-widget-advanced-chart.js",
        "embed-widget-technical-analysis.js",
        "embed-widget-screener.js",
        "embed-widget-crypto-coins-heatmap.js",
    ):
        assert widget in js
    assert "Math.random" not in js
    assert "Реальная торговля остаётся заблокированной" in js


def test_market_intelligence_owns_replay_and_analysis() -> None:
    js = (WEB2 / "market_intelligence_v33.js").read_text(encoding="utf-8")
    assert "/api/market-intelligence/snapshot" in js
    assert "/api/market-intelligence/replay" in js
    assert "Умный скринер" in js
    assert "Replay Lab" in js
    assert "не отправляет реальные ордера" in js


def test_recent_trades_backend_is_verified_and_no_fallback() -> None:
    py = (ROOT / "dashboard/market_data_api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/market/trades/{symbol}")' in py
    assert 'f"{_BYBIT_MARKET_URL}/recent-trade"' in py
    assert '"verified": True' in py
    assert '"synthetic_fallback_used": False' in py
    assert "random" not in py.lower()
