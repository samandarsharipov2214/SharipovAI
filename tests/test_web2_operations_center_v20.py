from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_operations_center_assets_are_connected() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    assert "/static/web2/operations_center_v20.css?" in index
    assert "/static/web2/operations_center_v20.js?" in index
    assert (WEB2 / "operations_center_v20.css").is_file()
    assert (WEB2 / "operations_center_v20.js").is_file()


def test_operations_center_uses_existing_read_only_health_apis() -> None:
    script = (WEB2 / "operations_center_v20.js").read_text(encoding="utf-8")
    assert "/api/system/health" in script
    assert "/api/system/recovery-plan" in script
    assert "Автовосстановление торговли запрещено" in script
    assert "ничего не перезапускает" in script
    assert "EXCHANGE_LIVE_TRADING_ENABLED" not in script
    assert "fetch(" in script
    assert "method: 'POST'" not in script
    assert 'method: "POST"' not in script


def test_operations_center_does_not_replace_existing_sections() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    required = [
        "market_terminal_v13.js",
        "ai_center_v14.js",
        "general_control_v15.js",
        "portfolio_risk_v16.js",
        "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
    ]
    for asset in required:
        assert asset in index
