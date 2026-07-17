from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_terminal_refreshes_verified_quote_with_rest_fallback() -> None:
    source = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    assert "/api/market/bybit-websocket/quote/" in source
    assert "/api/market/quote/" in source
    assert "setInterval(loadQuote, 2000)" in source
    assert "age <= 3 ? 'LIVE'" in source
    assert "document.hidden" in source
    assert "quoteBusy" in source


def test_terminal_uses_bounded_incremental_native_updates() -> None:
    source = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    assert "setInterval(loadBookAndTrades, 5000)" in source
    assert "setInterval(loadContext, 15000)" in source
    assert "Promise.allSettled" in source
    assert "bookBusy" in source
    assert "contextBusy" in source
    assert "renderLive" in source
    assert "Keep the last confirmed virtual-account state visible" in source


def test_public_websocket_is_enabled_without_live_trading() -> None:
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'FEATURE_BYBIT_WEBSOCKET: "1"' in compose
    assert 'BYBIT_WS_SYMBOLS: "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"' in compose
    assert 'EXCHANGE_LIVE_TRADING_ENABLED: "0"' in compose
    assert 'EXECUTION_KILL_SWITCH: "1"' in compose


def test_current_polish_height_fix_and_cache_busting_are_connected() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/site_polish_v23.css?" in index
    assert "/static/web2/tradingview_market_v32.css?v=32" in index
    assert "/static/web2/tradingview_market_v32.js?v=32" in index
    assert "/static/web2/tradingview_widget_height_fix_v34.css?v=34" in index
    assert "/static/web2/tradingview_widget_height_fix_v34.js?v=34" in index
    assert (WEB2 / "site_polish_v23.css").is_file()


def test_realtime_terminal_is_read_only() -> None:
    source = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    forbidden = (
        "method: 'POST'",
        'method: "POST"',
        "FEATURE_BYBIT_LIVE_EXECUTION",
        "/api/trading/",
        "Math.random",
    )
    for fragment in forbidden:
        assert fragment not in source
    assert "Реальная торговля остаётся заблокированной" in source
