from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_terminal_quote_refreshes_once_per_second_from_verified_stream() -> None:
    source = (WEB2 / "market_terminal_v13.js").read_text(encoding="utf-8")
    assert "const QUOTE_REFRESH_MS = 1000" in source
    assert "/api/market/bybit-websocket/quote/" in source
    assert "/api/market/quote/" in source
    assert "REST fallback" in source
    assert "LIVE · 1 СЕК" in source
    assert "setInterval(loadQuote, QUOTE_REFRESH_MS)" in source


def test_terminal_uses_incremental_updates_and_bounded_background_load() -> None:
    source = (WEB2 / "market_terminal_v13.js").read_text(encoding="utf-8")
    assert "const BOOK_REFRESH_MS = 3000" in source
    assert "const CANDLE_REFRESH_MS = 10000" in source
    assert "const CONTEXT_REFRESH_MS = 30000" in source
    assert "document.hidden" in source
    assert "quoteBusy" in source
    assert "bookBusy" in source
    assert "candleBusy" in source
    assert "setText('mtPrice'" in source
    assert "renderDynamicPanels" in source
    assert "setInterval(() => { if (activeMarket()) load(); }, 5000)" not in source


def test_public_websocket_is_enabled_for_all_terminal_symbols_without_trading() -> None:
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'FEATURE_BYBIT_WEBSOCKET: "1"' in compose
    assert 'BYBIT_WS_SYMBOLS: "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT"' in compose
    assert 'EXCHANGE_LIVE_TRADING_ENABLED: "0"' in compose
    assert 'EXECUTION_KILL_SWITCH: "1"' in compose


def test_polish_and_terminal_assets_are_connected() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/site_polish_v23.css?" in index
    assert "/static/web2/market_terminal_v13.css?" in index
    assert "/static/web2/market_terminal_v13.js?" in index
    assert (WEB2 / "site_polish_v23.css").is_file()


def test_realtime_terminal_is_read_only() -> None:
    source = (WEB2 / "market_terminal_v13.js").read_text(encoding="utf-8")
    forbidden = (
        "method: 'POST'",
        'method: "POST"',
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "FEATURE_BYBIT_LIVE_EXECUTION",
        "/api/trading/",
        "Math.random",
    )
    for fragment in forbidden:
        assert fragment not in source
