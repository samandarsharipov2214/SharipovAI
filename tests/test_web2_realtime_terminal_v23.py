from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_terminal_refreshes_verified_quote_and_runtime_truth() -> None:
    source = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    assert "/api/market/quote/" in source
    assert "/api/market/orderbook/" in source
    assert "/api/market/trades/" in source
    assert "/api/system/runtime-truth" in source
    assert "/api/market/bybit-websocket/quote/" not in source
    assert "document.hidden" in source
    assert "state.busy" in source


def test_terminal_uses_bounded_atomic_updates() -> None:
    source = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    assert "Promise.allSettled" in source
    assert "setInterval" in source
    assert "10000" in source
    assert "if (!active() || state.busy) return" in source
    assert "state.busy = true" in source
    assert "state.busy = false" in source
    assert "render()" in source


def test_public_websocket_is_enabled_without_live_trading() -> None:
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'FEATURE_BYBIT_WEBSOCKET: "1"' in compose
    assert 'BYBIT_WS_SYMBOLS: "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"' in compose
    assert 'EXCHANGE_LIVE_TRADING_ENABLED: "0"' in compose
    assert 'EXECUTION_KILL_SWITCH: "1"' in compose


def test_current_unified_interface_height_fix_and_cache_busting_are_connected() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/interface_v30.css?v=47" in index
    assert "/static/web2/site_polish_v23.css?" not in index
    assert "/static/web2/tradingview_market_v32.css?v=45" in index
    assert "/static/web2/tradingview_market_v32.js?v=45" in index
    assert "/static/web2/tradingview_widget_height_fix_v34.css?v=34" in index
    assert "/static/web2/tradingview_widget_height_fix_v34.js?v=34" in index
    assert (WEB2 / "interface_v30.css").is_file()


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
