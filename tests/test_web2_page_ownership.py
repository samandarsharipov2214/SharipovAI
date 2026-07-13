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
SYSTEM_STATUS = WEB2 / "system_status_v11.js"
INTERFACE = WEB2 / "interface_v30.css"


def test_page_runtime_script_order_and_cache_version():
    html = INDEX.read_text(encoding="utf-8")
    coordinator = html.index("navigation_coordinator_v23.js?v=25")
    core = html.index("web2.js?v=29")
    overview = html.index("overview_runtime_v25.js?v=30")
    decision = html.index("decision_runtime_v25.js?v=25")
    learning = html.index("learning_runtime_v25.js?v=25")
    exchange = html.index("exchange_execution_settings_v18.js?v=30")
    assert coordinator < core < overview < decision < learning < exchange
    assert "system_status_v11.js?v=29" in html
    assert "interface_v30.css?v=30" in html


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


def test_header_and_system_status_count_the_same_market_source():
    core = CORE.read_text(encoding="utf-8")
    status = SYSTEM_STATUS.read_text(encoding="utf-8")
    endpoint = "/api/market/bybit-websocket/status"
    assert endpoint in core
    assert endpoint in status


def test_system_status_is_live_and_omits_meaningless_placeholder_fields():
    source = SYSTEM_STATUS.read_text(encoding="utf-8")
    assert "AUTO_REFRESH_MS = 15000" in source
    assert "setInterval(updateClock, 1000)" in source
    assert "Текущее время" in source
    assert "Проверено ${seconds} сек назад" in source
    assert "Записей:" not in source
    assert "Состояние:" not in source
    assert "Как читать статусы" not in source
    assert "Ключ Bybit должен разрешать только чтение аккаунта" in source


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
    assert "Виртуальные операции" in execution
    assert "Реальные исполнения" in execution


def test_overview_supports_multiple_currencies_and_simple_money_precision():
    source = OVERVIEW.read_text(encoding="utf-8")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"):
        assert symbol in source
    assert "maximumFractionDigits:1" in source
    assert "entry_reason_ru" in source
    assert "signal_change_24h_percent" in source


def test_overview_defaults_to_rubles_and_uses_verified_rate_api():
    source = OVERVIEW.read_text(encoding="utf-8")
    assert "sharipovai-display-currency" in source
    assert "||'RUB'" in source
    assert "/api/currency/usd-rub" in source
    assert "rub_per_usdt_estimate" in source
    assert "Рубли ₽" in source
    assert "1 USDT ≈" in source
    assert "Math.round" in source


def test_trade_cards_explain_notional_quantity_price_and_fees():
    overview = OVERVIEW.read_text(encoding="utf-8")
    execution = EXECUTION_UI.read_text(encoding="utf-8")
    css = INTERFACE.read_text(encoding="utf-8")
    for source in (overview, execution):
        assert "Размер позиции" in source
        assert "Количество" in source
        assert "Результат движения цены" in source
        assert "Комиссии" in source
        assert "Чистый результат" in source
        assert "Показать" in source
        assert "notional" in source
        assert "quantity" in source
        assert "gross_pnl" in source
        assert "entry_fee" in source
    assert ".trade-card" in css
    assert ".trade-breakdown" in css
    assert "@media(max-width:560px)" in css


def test_trade_page_distinguishes_current_price_from_exit_price():
    source = EXECUTION_UI.read_text(encoding="utf-8")
    assert "Текущая цена" in source
    assert "Цена выхода" in source
    assert "цена справа является текущей, а не ценой выхода" in source
    assert "OPEN означает" in source
    assert "data-trade-filter" in source


def test_virtual_account_parses_nested_state_payload():
    source = EXECUTION_UI.read_text(encoding="utf-8")
    assert "raw?.state" in source
    assert "state.summary" in source
    assert "state.trades" in source
