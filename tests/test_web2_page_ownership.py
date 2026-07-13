from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"
COORDINATOR = WEB2 / "navigation_coordinator_v23.js"
CORE = WEB2 / "web2.js"
OVERVIEW = WEB2 / "overview_runtime_v25.js"
DECISION = WEB2 / "decision_runtime_v25.js"
LEARNING = WEB2 / "learning_runtime_v25.js"
EXECUTION_UI = WEB2 / "exchange_execution_settings_v18.js"


def test_page_runtime_script_order_and_cache_version():
    html = INDEX.read_text(encoding="utf-8")
    coordinator = html.index("navigation_coordinator_v23.js?v=25")
    core = html.index("web2.js?v=25")
    overview = html.index("overview_runtime_v25.js?v=25")
    decision = html.index("decision_runtime_v25.js?v=25")
    learning = html.index("learning_runtime_v25.js?v=25")
    exchange = html.index("exchange_execution_settings_v18.js?v=25")
    assert coordinator < core < overview < decision < learning < exchange


def test_one_explicit_owner_for_affected_pages():
    source = COORDINATOR.read_text(encoding="utf-8")
    assert "['overview', 'overview_runtime_v25.js']" in source
    assert "['decision', 'decision_runtime_v25.js']" in source
    assert "['portfolio', 'portfolio_risk_v16.js']" in source
    assert "['trades', 'exchange_execution_settings_v18.js']" in source
    assert "['learning', 'learning_runtime_v25.js']" in source
    assert "version: 25" in source


def test_legacy_core_does_not_render_owned_pages_or_poll_market():
    source = CORE.read_text(encoding="utf-8")
    assert "function renderChat()" in source
    assert "function overview()" not in source
    assert "function marketPage()" not in source
    assert "restartMarketTimer" not in source
    assert "loadMarket(" not in source
    assert "setInterval(() => { loadHeaderStatus()" in source


def test_virtual_first_overview_decision_learning_and_trades_exist():
    overview = OVERVIEW.read_text(encoding="utf-8")
    decision = DECISION.read_text(encoding="utf-8")
    learning = LEARNING.read_text(encoding="utf-8")
    execution = EXECUTION_UI.read_text(encoding="utf-8")
    assert "/api/virtual-account/state" in overview
    assert "Реальные ордера" in overview
    assert "/api/virtual-account/state" in decision
    assert "Каноническое решение" in decision
    assert "Виртуальный контур" in decision
    assert "/api/virtual-account/trades" in learning
    assert "Закрытые виртуальные сделки" in learning
    assert "/api/virtual-account/trades" in execution
    assert "Виртуальные сделки по рыночным ценам" in execution
    assert "Реальные исполнения Bybit" in execution


def test_virtual_account_parses_nested_state_payload():
    source = EXECUTION_UI.read_text(encoding="utf-8")
    assert "raw?.state" in source
    assert "state.summary" in source
    assert "state.trades" in source
