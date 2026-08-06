from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_verified_web2_shell_remains_primary_interface() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    host = (ROOT / "dashboard" / "web2_host.py").read_text(encoding="utf-8")
    for marker in (
        "SharipovAI OS",
        "overview_runtime_v44.js",
        "canonical_pages_v45.js",
        "navigation_coordinator_v44.js",
        "web2_shell_v44.js",
        "runtime_render_guard_v24.js",
        "interface_v30.css",
        "tradingview_market_v32.js",
        "tradingview_widget_height_fix_v34.js",
    ):
        assert marker in index
    assert "overview_runtime_v25.js" not in index
    assert "sections_v10.js" not in index
    assert '"/control"' in host
    assert "no-store, no-cache, must-revalidate" in host


def test_verified_pages_keep_trade_explanations_on_canonical_state() -> None:
    source = (WEB2 / "overview_runtime_v44.js").read_text(encoding="utf-8") + (WEB2 / "canonical_pages_v45.js").read_text(encoding="utf-8")
    interface = (WEB2 / "interface_v30.css").read_text(encoding="utf-8")
    for marker in (
        "CouncilAuthorizedPaperLoop",
        "Размер позиции",
        "Количество",
        "Текущая цена",
        "Цена выхода",
        "Комиссии",
        "Чистый результат",
        "entry_reason_ru",
        "/api/system/runtime-truth",
    ):
        assert marker in source
    assert "/api/virtual-account/state" not in source
    assert ".trade-card" in interface
    assert ".trade-breakdown" in interface


def test_verified_market_terminal_keeps_tradingview_and_canonical_market_sources() -> None:
    market = (WEB2 / "tradingview_market_v32.js").read_text(encoding="utf-8")
    height_fix = (WEB2 / "tradingview_widget_height_fix_v34.js").read_text(encoding="utf-8")
    for marker in (
        "/api/market/quote/",
        "/api/market/orderbook/",
        "/api/market/trades/",
        "/api/system/runtime-truth",
    ):
        assert marker in market
    assert "/api/virtual-account/state" not in market
    assert "frame.style.height" in height_fix
