from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"
INDEX = WEB2 / "index.html"
LEGACY_SCRIPT = WEB2 / "sections_v10.js"
LEGACY_STYLE = WEB2 / "sections_v10.css"


def test_legacy_sections_assets_may_remain_but_are_not_runtime_owners() -> None:
    assert INDEX.exists()
    assert LEGACY_SCRIPT.exists()
    assert LEGACY_STYLE.exists()
    html = INDEX.read_text(encoding="utf-8")
    assert "sections_v10.js" not in html
    coordinator = (WEB2 / "navigation_coordinator_v23.js").read_text(encoding="utf-8")
    assert "value.includes('sections_v10.js')" in coordinator


def test_all_current_sections_are_present() -> None:
    html = INDEX.read_text(encoding="utf-8")
    pages = [
        "overview",
        "market",
        "decision",
        "portfolio",
        "trades",
        "bots",
        "chat",
        "news",
        "risk",
        "bybit",
        "learning",
        "control",
        "evidence",
        "virtual",
        "campaigns",
        "reports",
        "settings",
    ]
    for page in pages:
        assert f'data-page="{page}"' in html
    assert "sections_v10.css?" in html


def test_specialized_current_owners_use_real_data_routes() -> None:
    sources = "\n".join(
        (WEB2 / filename).read_text(encoding="utf-8")
        for filename in (
            "overview_runtime_v25.js",
            "tradingview_market_v32.js",
            "ai_center_v14.js",
            "news_center_v12.js",
            "portfolio_risk_v16.js",
            "learning_runtime_v25.js",
            "learning_evidence_reports_v17.js",
            "general_control_v15.js",
            "exchange_execution_settings_v18.js",
            "campaign_operations_v36.js",
        )
    )
    required_routes = [
        "/api/exchange/account/snapshot",
        "/api/ai-bots",
        "/api/social-news",
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/virtual-account/state",
        "/api/ai-control-center/daily-report",
        "/api/campaigns/operations",
    ]
    for route in required_routes:
        assert route in sources


def test_truthful_fallbacks_are_preserved_by_current_shell_and_guard() -> None:
    html = INDEX.read_text(encoding="utf-8")
    guard = (WEB2 / "truth_guard.js").read_text(encoding="utf-8")
    current_sources = "\n".join(
        (WEB2 / filename).read_text(encoding="utf-8")
        for filename in (
            "overview_runtime_v25.js",
            "ai_center_v14.js",
            "news_center_v12.js",
            "learning_evidence_reports_v17.js",
        )
    )
    assert "Интерфейс не подменяет отсутствующие значения" in html
    assert "SYNTHETIC_PHRASES" in guard
    assert "НЕТ ПОДТВЕРЖДЁННОГО СОБЫТИЯ" in guard
    assert "Evidence Vault" in guard
    assert "Math.random" not in current_sources


def test_news_ai_and_campaign_sections_have_specialized_renderers() -> None:
    assert "Открыть источник" in (WEB2 / "news_center_v12.js").read_text(encoding="utf-8")
    ai = (WEB2 / "ai_center_v14.js").read_text(encoding="utf-8")
    assert "Карта ИИ" in ai
    assert "Журнал работы" in ai
    campaign = (WEB2 / "campaign_operations_v36.js").read_text(encoding="utf-8")
    assert "Campaign Operations" in campaign
    assert "final_report" in campaign
