from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / 'dashboard' / 'static' / 'web2' / 'index.html'
GUARD = ROOT / 'dashboard' / 'static' / 'web2' / 'runtime_render_guard_v24.js'
EXECUTION_UI = ROOT / 'dashboard' / 'static' / 'web2' / 'exchange_execution_settings_v18.js'


def test_page_ownership_script_order():
    html = INDEX.read_text(encoding='utf-8')
    assert html.index('navigation_coordinator_v23.js') < html.index('runtime_render_guard_v24.js') < html.index('web2.js?v=20')


def test_page_ownership_markers_present():
    source = GUARD.read_text(encoding='utf-8')
    assert "page === 'overview'" in source
    assert "page === 'market'" in source
    assert 'legacyOverviewMarkers' in source
    assert 'isLegacyOverwrite(value)' in source


def test_trades_page_uses_virtual_trade_api_and_labels_real_orders_separately():
    source = EXECUTION_UI.read_text(encoding='utf-8')
    html = INDEX.read_text(encoding='utf-8')
    assert "/api/virtual-account/trades" in source
    assert "Виртуальные сделки по рыночным ценам" in source
    assert "Реальные исполнения Bybit" in source
    assert "Реальные ордера" in source
    assert "exchange_execution_settings_v18.js?v=25" in html


def test_virtual_account_parses_nested_state_payload():
    source = EXECUTION_UI.read_text(encoding='utf-8')
    assert "raw?.state" in source
    assert "state.summary" in source
    assert "state.trades" in source
