from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_navigation_coordinator_is_loaded_before_renderers() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    coordinator = "/static/web2/navigation_coordinator_v22.js?v=22"
    assert coordinator in index
    assert index.index(coordinator) < index.index("/static/web2/web2.js")
    assert index.index(coordinator) < index.index("/static/web2/system_status_v11.js")


def test_exclusive_pages_own_the_shared_content_container() -> None:
    source = (WEB2 / "navigation_coordinator_v22.js").read_text(encoding="utf-8")
    assert "system-status" in source
    assert "system_status_v11.js" in source
    assert "operations" in source
    assert "operations_center_v20.js" in source
    assert "Object.defineProperty(content, 'innerHTML'" in source
    assert "if (activeOwner)" in source
    assert "if (callerOwner) return false" in source


def test_navigation_fix_does_not_enable_trading_or_send_requests() -> None:
    source = (WEB2 / "navigation_coordinator_v22.js").read_text(encoding="utf-8")
    forbidden = (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EXCHANGE_LIVE_TRADING_ENABLED",
        "TESTNET_EXECUTION_ENABLED",
        "method: 'POST'",
        'method: "POST"',
    )
    for fragment in forbidden:
        assert fragment not in source
