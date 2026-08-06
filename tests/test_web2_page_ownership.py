from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"
COORDINATOR = WEB2 / "navigation_coordinator_v44.js"
RENDER_GUARD = WEB2 / "runtime_render_guard_v24.js"
SHELL = WEB2 / "web2_shell_v44.js"
OVERVIEW = WEB2 / "overview_runtime_v44.js"
AI_CENTER = WEB2 / "ai_center_v44.js"
MARKET = WEB2 / "tradingview_market_v32.js"
MARKET_CSS = WEB2 / "tradingview_market_v32.css"
DECISION = WEB2 / "decision_runtime_v25.js"
LEARNING = WEB2 / "learning_runtime_v25.js"
EXECUTION_UI = WEB2 / "exchange_execution_settings_v18.js"
SYSTEM_STATUS = WEB2 / "system_status_v44.js"
CAMPAIGNS = WEB2 / "campaign_operations_v36.js"
INTERFACE = WEB2 / "interface_v30.css"
WEB2_HOST = ROOT / "dashboard" / "web2_host.py"


def test_page_runtime_coordinator_precedes_every_current_renderer():
    html = INDEX.read_text(encoding="utf-8")
    coordinator = html.index("navigation_coordinator_v44.js?v=44")
    for asset in (
        "web2_shell_v44.js?v=44",
        "overview_runtime_v44.js?v=44",
        "ai_center_v44.js?v=44",
        "system_status_v44.js?v=44",
        "decision_runtime_v25.js?v=25",
        "news_center_v12.js?v=25",
        "tradingview_market_v32.js?v=32",
        "market_intelligence_v33.js?v=33",
        "learning_runtime_v25.js?v=25",
        "exchange_execution_settings_v18.js?v=30",
        "campaign_operations_v36.js?v=36",
    ):
        assert coordinator < html.index(asset)
    assert "runtime_render_guard_v24.js?v=31" in html
    assert "interface_v30.css?v=30" in html
    assert "tradingview_market_v32.css?v=32" in html
    assert "campaign_operations_v36.css?v=36" in html


def test_obsolete_truth_renderers_are_not_loaded():
    html = INDEX.read_text(encoding="utf-8")
    for obsolete in (
        "sections_v10.js",
        "market_terminal_v13.js",
        "market_terminal_v13.css",
        "web2.js?",
        "overview_runtime_v25.js",
        "ai_center_v14.js",
        "system_status_v11.js",
    ):
        assert obsolete not in html


def test_one_explicit_owner_for_every_current_page():
    source = COORDINATOR.read_text(encoding="utf-8")
    expected = {
        "overview": "overview_runtime_v44.js",
        "market": "tradingview_market_v32.js",
        "decision": "decision_runtime_v25.js",
        "portfolio": "portfolio_risk_v16.js",
        "trades": "exchange_execution_settings_v18.js",
        "bots": "ai_center_v44.js",
        "chat": "web2_shell_v44.js",
        "news": "news_center_v12.js",
        "risk": "portfolio_risk_v16.js",
        "bybit": "exchange_execution_settings_v18.js",
        "learning": "learning_runtime_v25.js",
        "control": "general_control_v15.js",
        "evidence": "learning_evidence_reports_v17.js",
        "virtual": "exchange_execution_settings_v18.js",
        "campaigns": "campaign_operations_v36.js",
        "reports": "learning_evidence_reports_v17.js",
        "settings": "exchange_execution_settings_v18.js",
        "system-status": "system_status_v44.js",
        "operations": "operations_center_v20.js",
    }
    for page, owner in expected.items():
        assert f"['{page}', '{owner}']" in source
    assert "const VERSION = 44" in source
    assert "value.includes('sections_v10.js')" in source
    assert "value.includes('market_terminal_v13.js')" in source


def test_render_guard_blocks_known_legacy_overview_signatures():
    source = RENDER_GUARD.read_text(encoding="utf-8")
    assert "const VERSION = 31" in source
    assert "Фактическое состояние системы без выдуманных показателей" in source
    assert "Фактическая сводка SharipovAI по всем рабочим контурам" in source
    assert "Последнее решение" in source


def test_shell_html_is_never_cached():
    source = WEB2_HOST.read_text(encoding="utf-8")
    assert '"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"' in source
    assert '"Pragma": "no-cache"' in source
    assert "headers=_NO_CACHE_HEADERS" in source


def test_shell_uses_one_runtime_truth_and_does_not_score_legacy_urls():
    source = SHELL.read_text(encoding="utf-8")
    assert "function renderChat()" in source
    assert "/api/system/runtime-truth" in source
    assert "/api/run" not in source
    assert "/api/ai-bots" not in source
    assert "/api/virtual-account/state" not in source
    assert "setInterval" in source


def test_truth_pages_share_the_same_canonical_runtime_source():
    for source in (
        SHELL.read_text(encoding="utf-8"),
        OVERVIEW.read_text(encoding="utf-8"),
        AI_CENTER.read_text(encoding="utf-8"),
        SYSTEM_STATUS.read_text(encoding="utf-8"),
    ):
        assert "/api/system/runtime-truth" in source
    assert "/api/market/stream/status" in SYSTEM_STATUS.read_text(encoding="utf-8")


def test_tradingview_market_embeds_supported_official_widgets():
    source = MARKET.read_text(encoding="utf-8")
    expected_scripts = (
        "embed-widget-advanced-chart.js",
        "embed-widget-technical-analysis.js",
        "embed-widget-screener.js",
        "embed-widget-crypto-coins-heatmap.js",
        "embed-widget-market-overview.js",
        "embed-widget-events.js",
        "embed-widget-timeline.js",
    )
    for script in expected_scripts:
        assert f"https://s3.tradingview.com/external-embedding/{script}" in source
    assert "Он не передаёт ордера" in source
    assert "Реальная торговля остаётся заблокированной" in source


def test_tradingview_market_has_supported_pairs_and_responsive_layout():
    source = MARKET.read_text(encoding="utf-8")
    css = MARKET_CSS.read_text(encoding="utf-8")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"):
        assert symbol in source
    assert "setInterval(loadQuote, 2000)" in source
    assert "setInterval(loadBookAndTrades, 5000)" in source
    assert ".tv32-widget-host" in css
    assert "@media(max-width:760px)" in css


def test_overview_uses_canonical_paper_truth_and_verified_fx():
    source = OVERVIEW.read_text(encoding="utf-8")
    assert "/api/system/runtime-truth" in source
    assert "/api/virtual-account/state" not in source
    assert "CouncilAuthorizedPaperLoop" in source
    assert "sharipovai-display-currency" in source
    assert "/api/currency/usd-rub" in source
    assert "rub_per_usdt_estimate" in source
    assert "Рубли ₽" in source


def test_overview_trade_cards_explain_value_and_fees():
    overview = OVERVIEW.read_text(encoding="utf-8")
    execution = EXECUTION_UI.read_text(encoding="utf-8")
    css = INTERFACE.read_text(encoding="utf-8")
    for marker in ("Размер", "Комиссии", "Net PnL", "notional", "entry_reason_ru"):
        assert marker in overview
    for marker in ("Размер позиции", "Количество", "Комиссии", "Чистый результат"):
        assert marker in execution
    assert ".trade-card" in css
    assert ".trade-breakdown" in css


def test_existing_decision_learning_execution_and_campaign_pages_remain_available():
    decision = DECISION.read_text(encoding="utf-8")
    learning = LEARNING.read_text(encoding="utf-8")
    execution = EXECUTION_UI.read_text(encoding="utf-8")
    campaigns = CAMPAIGNS.read_text(encoding="utf-8")
    assert "Каноническое решение" in decision
    assert "Закрытые виртуальные сделки" in learning
    assert "Виртуальные операции" in execution
    for marker in ("/api/campaigns/operations", "matched_fills", "final_report"):
        assert marker in campaigns
    assert "/v5/order/create" not in campaigns
