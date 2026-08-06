from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_operations_center_assets_are_connected() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/operations_center_v20.css?" in index
    assert "/static/web2/operations_center_v20.js?" in index
    assert index.index("operations_center_v20.css") < index.index("operations_center_v20.js")


def test_operations_center_uses_existing_read_only_health_apis() -> None:
    script = (WEB2 / "operations_center_v20.js").read_text(encoding="utf-8")
    assert "/api/system/health" in script
    assert "/api/system/recovery-plan" in script
    assert "Автовосстановление торговли запрещено" in script
    assert "ничего не перезапускает" in script
    assert "fetch(" in script
    assert "method: 'POST'" not in script
    assert 'method: "POST"' not in script


def test_operations_center_coexists_with_current_canonical_owners() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    required = (
        "navigation_coordinator_v44.js",
        "overview_runtime_v44.js",
        "canonical_pages_v45.js",
        "ai_center_v44.js",
        "system_status_v44.js",
        "tradingview_market_v32.js",
        "market_intelligence_v33.js",
        "campaign_operations_v36.js",
    )
    for asset in required:
        assert asset in index
    for retired in (
        "general_control_v15.js",
        "portfolio_risk_v16.js",
        "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
        "market_terminal_v13.js",
        "ai_center_v14.js",
    ):
        assert retired not in index
