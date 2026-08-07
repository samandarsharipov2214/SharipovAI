from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"
COORDINATOR = WEB2 / "navigation_coordinator_v44.js"
RENDER_GUARD = WEB2 / "runtime_render_guard_v24.js"
SHELL = WEB2 / "web2_shell_v44.js"
OVERVIEW = WEB2 / "overview_runtime_v44.js"
CANONICAL = WEB2 / "canonical_pages_v45.js"
AI_CENTER = WEB2 / "ai_center_v44.js"
MARKET = WEB2 / "tradingview_market_v32.js"
MARKET_CSS = WEB2 / "tradingview_market_v32.css"
SYSTEM_STATUS = WEB2 / "system_status_v44.js"
CAMPAIGNS = WEB2 / "campaign_operations_v36.js"
INTERFACE = WEB2 / "interface_v30.css"
WEB2_HOST = ROOT / "dashboard" / "web2_host.py"


def test_page_runtime_coordinator_precedes_every_current_renderer():
    html = INDEX.read_text(encoding="utf-8")
    coordinator = html.index("navigation_coordinator_v44.js?v=45")
    for asset in (
        "web2_shell_v44.js?v=47",
        "overview_runtime_v44.js?v=45",
        "canonical_pages_v45.js?v=45",
        "runtime_trace_v46.js?v=46",
        "ai_center_v44.js?v=45",
        "system_status_v44.js?v=45",
        "news_center_v12.js?v=25",
        "tradingview_market_v32.js?v=45",
        "market_intelligence_v33.js?v=33",
        "campaign_operations_v36.js?v=36",
    ):
        assert coordinator < html.index(asset)
    assert "runtime_render_guard_v24.js?v=31" in html
    assert "interface_v30.css?v=47" in html
    assert "tradingview_market_v32.css?v=45" in html
    assert "campaign_operations_v36.css?v=36" in html


def test_obsolete_truth_renderers_are_not_loaded():
    html = INDEX.read_text(encoding="utf-8")
    for obsolete in (
        "sections_v10.js",
        "market_terminal_v13.js",
        "market_terminal_v13.css",
        "web2.js?",
        "overview_runtime_v25.js",
        "decision_runtime_v25.js",
        "ai_center_v14.js",
        "system_status_v11.js",
        "general_control_v15.js",
        "portfolio_risk_v16.js",
        "learning_runtime_v25.js",
        "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
    ):
        assert obsolete not in html


def test_one_explicit_owner_for_every_current_page():
    source = COORDINATOR.read_text(encoding="utf-8")
    expected = {
        "overview": "overview_runtime_v44.js",
        "market": "tradingview_market_v32.js",
        "decision": "canonical_pages_v45.js",
        "portfolio": "canonical_pages_v45.js",
        "trades": "canonical_pages_v45.js",
        "bots": "ai_center_v44.js",
        "chat": "web2_shell_v44.js",
        "news": "news_center_v12.js",
        "risk": "canonical_pages_v45.js",
        "bybit": "canonical_pages_v45.js",
        "learning": "canonical_pages_v45.js",
        "control": "canonical_pages_v45.js",
        "evidence": "canonical_pages_v45.js",
        "virtual": "canonical_pages_v45.js",
        "campaigns": "campaign_operations_v36.js",
        "reports": "canonical_pages_v45.js",
        "settings": "canonical_pages_v45.js",
        "system-status": "system_status_v44.js",
        "operations": "operations_center_v20.js",
    }
    for page, owner in expected.items():
        assert f"['{page}', '{owner}']" in source
    assert "const VERSION = 45" in source
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


def test_all_truth_pages_share_the_same_canonical_runtime_source():
    for source in (
        SHELL.read_text(encoding="utf-8"),
        OVERVIEW.read_text(encoding="utf-8"),
        CANONICAL.read_text(encoding="utf-8"),
        AI_CENTER.read_text(encoding="utf-8"),
        SYSTEM_STATUS.read_text(encoding="utf-8"),
        MARKET.read_text(encoding="utf-8"),
    ):
        assert "/api/system/runtime-truth" in source
    combined = CANONICAL.read_text(encoding="utf-8") + MARKET.read_text(encoding="utf-8")
    for endpoint in ("/api/run", "/api/ai-bots", "/api/virtual-account/state", "/api/virtual-account/trades"):
        assert endpoint not in combined


def test_tradingview_market_embeds_all_supported_official_widgets():
    source = MARKET.read_text(encoding="utf-8")
    for script in (
        "embed-widget-advanced-chart.js",
        "embed-widget-technical-analysis.js",
        "embed-widget-screener.js",
        "embed-widget-crypto-coins-heatmap.js",
        "embed-widget-market-overview.js",
        "embed-widget-events.js",
        "embed-widget-timeline.js",
    ):
        assert f"https://s3.tradingview.com/external-embedding/{script}" in source
    for label in ("График", "Теханализ", "Скринер", "Тепловая карта", "Обзор рынков", "Календарь", "Новости TradingView"):
        assert label in source
    assert "allow_symbol_change: true" in source
    assert "studies: ['STD;RSI', 'STD;MACD']" in source
    assert "Он не передаёт ордера" in source
    assert "Реальная торговля остаётся заблокированной" in source


def test_tradingview_market_has_supported_pairs_live_sources_and_responsive_layout():
    source = MARKET.read_text(encoding="utf-8")
    css = MARKET_CSS.read_text(encoding="utf-8")
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"):
        assert symbol in source
    for endpoint in ("/api/market/quote/", "/api/market/orderbook/", "/api/market/trades/", "/api/system/runtime-truth"):
        assert endpoint in source
    assert "setInterval" in source
    assert ".tv32-widget-host" in css
    assert "@media(max-width:760px)" in css


def test_overview_and_canonical_pages_keep_explanations_and_verified_fx():
    overview = OVERVIEW.read_text(encoding="utf-8")
    canonical = CANONICAL.read_text(encoding="utf-8")
    css = INTERFACE.read_text(encoding="utf-8")
    assert "/api/currency/usd-rub" in overview
    assert "rub_per_usdt_estimate" in overview
    assert "Рубли ₽" in overview
    for marker in ("Размер позиции", "Количество", "Текущая цена", "Цена выхода", "Комиссии", "Чистый результат", "entry_reason_ru"):
        assert marker in canonical
    assert ".trade-card" in css
    assert ".trade-breakdown" in css


def test_decision_learning_execution_and_campaign_capabilities_remain_available():
    canonical = CANONICAL.read_text(encoding="utf-8")
    campaigns = CAMPAIGNS.read_text(encoding="utf-8")
    for marker in (
        "Каноническое решение",
        "Центр обучения",
        "Хранилище доказательств",
        "Виртуальные операции",
        "Канонический виртуальный счёт",
        "Bybit read-only",
        "/api/autonomous-paper/events",
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
    ):
        assert marker in canonical
    for marker in ("/api/campaigns/operations", "matched_fills", "orphan_execution_count", "duplicate_order_count", "unresolved_order_count", "actual_fee_total", "final_report"):
        assert marker in campaigns
    assert "/v5/order/create" not in campaigns
