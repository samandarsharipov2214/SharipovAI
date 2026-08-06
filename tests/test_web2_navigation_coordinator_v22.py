from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_navigation_coordinator_is_loaded_before_renderers() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    coordinator = "/static/web2/navigation_coordinator_v44.js?v=45"
    assert coordinator in index
    for renderer in (
        "/static/web2/web2_shell_v44.js",
        "/static/web2/overview_runtime_v44.js",
        "/static/web2/canonical_pages_v45.js",
        "/static/web2/ai_center_v44.js",
        "/static/web2/system_status_v44.js",
        "/static/web2/tradingview_market_v32.js",
        "/static/web2/campaign_operations_v36.js",
    ):
        assert index.index(coordinator) < index.index(renderer)


def test_every_visible_page_has_one_current_content_owner() -> None:
    source = (WEB2 / "navigation_coordinator_v44.js").read_text(encoding="utf-8")
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
    assert "Object.defineProperty(content, 'innerHTML'" in source
    assert "callerOwner === activeOwner" in source
    assert "return !callerOwner" in source
    assert "sections_v10.js" in source
    assert "market_terminal_v13.js" in source


def test_navigation_preserves_labels_hash_and_accessibility() -> None:
    source = (WEB2 / "navigation_coordinator_v44.js").read_text(encoding="utf-8")
    assert "PAGE_LABELS" in source
    assert "campaigns: 'Кампании'" in source
    assert "aria-current" in source
    assert "history.replaceState" in source
    assert "hashchange" in source
    assert "CSS.escape" in source


def test_navigation_does_not_enable_trading_or_send_requests() -> None:
    source = (WEB2 / "navigation_coordinator_v44.js").read_text(encoding="utf-8")
    for fragment in ("fetch(", "XMLHttpRequest", "WebSocket(", "method: 'POST'", 'method: "POST"'):
        assert fragment not in source
