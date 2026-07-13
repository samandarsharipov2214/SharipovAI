from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_navigation_coordinator_is_loaded_before_renderers() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    coordinator = "/static/web2/navigation_coordinator_v23.js?v=23"
    assert coordinator in index
    assert index.index(coordinator) < index.index("/static/web2/web2.js")
    assert index.index(coordinator) < index.index("/static/web2/system_status_v11.js")
    assert index.index(coordinator) < index.index("/static/web2/market_terminal_v13.js")


def test_every_visible_page_has_one_content_owner() -> None:
    source = (WEB2 / "navigation_coordinator_v23.js").read_text(encoding="utf-8")
    expected = {
        "overview": "sections_v10.js",
        "market": "market_terminal_v13.js",
        "decision": "sections_v10.js",
        "portfolio": "portfolio_risk_v16.js",
        "trades": "exchange_execution_settings_v18.js",
        "bots": "ai_center_v14.js",
        "chat": "web2.js",
        "news": "news_center_v12.js",
        "risk": "portfolio_risk_v16.js",
        "bybit": "exchange_execution_settings_v18.js",
        "learning": "learning_evidence_reports_v17.js",
        "control": "general_control_v15.js",
        "evidence": "learning_evidence_reports_v17.js",
        "virtual": "exchange_execution_settings_v18.js",
        "reports": "learning_evidence_reports_v17.js",
        "settings": "exchange_execution_settings_v18.js",
        "system-status": "system_status_v11.js",
        "operations": "operations_center_v20.js",
    }
    for page, owner in expected.items():
        assert f"['{page}', '{owner}']" in source
    assert "Object.defineProperty(content, 'innerHTML'" in source
    assert "callerOwner === activeOwner" in source
    assert "if (callerOwner) return false" in source


def test_navigation_preserves_labels_hash_and_accessibility() -> None:
    source = (WEB2 / "navigation_coordinator_v23.js").read_text(encoding="utf-8")
    assert "PAGE_LABELS" in source
    assert "aria-current" in source
    assert "history.replaceState" in source
    assert "hashchange" in source
    assert "CSS.escape" in source


def test_navigation_fix_does_not_enable_trading_or_send_requests() -> None:
    source = (WEB2 / "navigation_coordinator_v23.js").read_text(encoding="utf-8")
    forbidden = (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket(",
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "TESTNET_EXECUTION_ENABLED",
        "method: 'POST'",
        'method: "POST"',
    )
    for fragment in forbidden:
        assert fragment not in source
