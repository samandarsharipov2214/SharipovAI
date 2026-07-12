from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_site_files_removed() -> None:
    assert not (ROOT / "dashboard" / "templates" / "index.html").exists()
    assert not (ROOT / "dashboard" / "static" / "mini-app-live.js").exists()


def test_new_site_is_the_only_ui_shell() -> None:
    index = (ROOT / "dashboard" / "static" / "web2" / "index.html").read_text(encoding="utf-8")
    required_pages = (
        "overview", "market", "decision", "portfolio", "trades", "bots", "chat", "news",
        "risk", "bybit", "learning", "control", "evidence", "virtual", "reports", "settings",
    )
    for page in required_pages:
        assert f'data-page="{page}"' in index
    assert "mini-app-live.js" not in index
    assert "dashboard/static/web2" not in index


def test_new_site_keeps_migrated_modules() -> None:
    index = (ROOT / "dashboard" / "static" / "web2" / "index.html").read_text(encoding="utf-8")
    expected_assets = (
        "news_center_v12.js",
        "market_terminal_v13.js",
        "ai_center_v14.js",
        "general_control_v15.js",
        "portfolio_risk_v16.js",
        "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
    )
    for asset in expected_assets:
        assert asset in index
