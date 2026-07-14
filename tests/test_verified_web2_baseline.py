from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_verified_web2_shell_remains_primary_interface() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    host = (ROOT / "dashboard" / "web2_host.py").read_text(encoding="utf-8")

    assert "SharipovAI OS" in index
    assert "overview_runtime_v25.js" in index
    assert "navigation_coordinator_v23.js" in index
    assert "runtime_render_guard_v24.js" in index
    assert "interface_v30.css" in index
    assert "tradingview_market_v32.js" in index
    assert "tradingview_widget_height_fix_v34.js" in index
    assert "sections_v10.js" not in index
    assert '"/control"' in host
    assert "no-store, no-cache, must-revalidate" in host


def test_verified_overview_keeps_user_requested_trade_explanations() -> None:
    overview = (WEB2 / "overview_runtime_v25.js").read_text(encoding="utf-8")
    interface = (WEB2 / "interface_v30.css").read_text(encoding="utf-8")

    for marker in (
        "Размер позиции",
        "Результат движения цены",
        "Комиссии",
        "Чистый результат",
        "entry_reason_ru",
        "signal_change_24h_percent",
    ):
        assert marker in overview
    assert ".trade-card" in interface
    assert ".trade-breakdown" in interface


def test_verified_market_terminal_keeps_tradingview_and_live_market_sources() -> None:
    market = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    height_fix = (WEB2 / "tradingview_widget_height_fix_v34.js").read_text(encoding="utf-8")

    for marker in (
        "/api/market/bybit-websocket/quote/",
        "/api/market/orderbook/",
        "/api/market/trades/",
        "/api/virtual-account/state",
    ):
        assert marker in market
    assert "frame.style.height" in height_fix
