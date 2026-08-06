from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_web2_host_is_the_only_production_ui_owner() -> None:
    host = (ROOT / "dashboard" / "web2_host.py").read_text(encoding="utf-8")
    assert 'WEB2_DIR = Path(__file__).resolve().parent / "static" / "web2"' in host
    assert 'WEB2_INDEX = WEB2_DIR / "index.html"' in host
    assert "return FileResponse(WEB2_INDEX" in host
    assert "no-store, no-cache, must-revalidate" in host
    assert "templates/index.html" not in host


def test_current_site_contains_every_visible_page_and_no_legacy_script() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    required_pages = (
        "overview", "market", "decision", "portfolio", "trades", "bots", "chat",
        "news", "risk", "bybit", "learning", "control", "evidence", "virtual",
        "campaigns", "reports", "settings",
    )
    for page in required_pages:
        assert f'data-page="{page}"' in index
    for legacy in (
        "mini-app-live.js", "sections_v10.js", "market_terminal_v13.js",
        "overview_runtime_v25.js", "decision_runtime_v25.js", "ai_center_v14.js",
        "system_status_v11.js", "general_control_v15.js", "portfolio_risk_v16.js",
        "learning_runtime_v25.js", "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
    ):
        assert legacy not in index


def test_current_site_keeps_verified_modules_and_canonical_truth_owners() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    expected_assets = (
        "navigation_coordinator_v44.js",
        "web2_shell_v44.js",
        "overview_runtime_v44.js",
        "canonical_pages_v45.js",
        "ai_center_v44.js",
        "system_status_v44.js",
        "news_center_v12.js",
        "tradingview_market_v32.js",
        "market_intelligence_v33.js",
        "campaign_operations_v36.js",
    )
    for asset in expected_assets:
        assert asset in index
