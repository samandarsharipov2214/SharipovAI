from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def _text(name: str) -> str:
    return (WEB2 / name).read_text(encoding="utf-8")


def _loaded_local_scripts() -> tuple[str, ...]:
    index = _text("index.html")
    sources = re.findall(r'<script[^>]+src="/static/web2/([^"?]+)(?:\?[^"}]*)?"', index)
    return tuple(dict.fromkeys(sources))


def test_web2_loads_only_current_canonical_truth_owners() -> None:
    index = _text("index.html")
    for script in (
        "navigation_coordinator_v44.js",
        "web2_shell_v44.js",
        "overview_runtime_v44.js",
        "canonical_pages_v45.js",
        "tradingview_market_v32.js",
        "ai_center_v44.js",
        "system_status_v44.js",
    ):
        assert script in index

    for legacy in (
        "navigation_coordinator_v23.js",
        "web2.js?",
        "canonical_runtime_ui_v44.js",
        "overview_runtime_v25.js",
        "decision_runtime_v25.js",
        "general_control_v15.js",
        "portfolio_risk_v16.js",
        "learning_runtime_v25.js",
        "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
        "system_status_v11.js",
        "ai_center_v14.js",
    ):
        assert legacy not in index


def test_navigation_coordinator_assigns_one_canonical_owner_per_truth_page() -> None:
    coordinator = _text("navigation_coordinator_v44.js")
    assert "const VERSION = 45" in coordinator
    assert "['overview', 'overview_runtime_v44.js']" in coordinator
    assert "['market', 'tradingview_market_v32.js']" in coordinator
    assert "['bots', 'ai_center_v44.js']" in coordinator
    assert "['system-status', 'system_status_v44.js']" in coordinator
    assert "['chat', 'web2_shell_v44.js']" in coordinator
    for page in ("decision", "portfolio", "trades", "risk", "bybit", "learning", "control", "evidence", "virtual", "reports", "settings"):
        assert f"['{page}', 'canonical_pages_v45.js']" in coordinator


def test_every_loaded_local_script_is_free_of_legacy_runtime_consumers() -> None:
    loaded = _loaded_local_scripts()
    assert loaded
    forbidden = (
        "/api/run",
        "/api/ai-bots",
        "/api/virtual-account/state",
        "/api/virtual-account/trades",
        "/api/paper-activity/state",
        "/api/paper-activity/trades",
    )
    offenders: dict[str, list[str]] = {}
    for name in loaded:
        source = _text(name)
        matches = [endpoint for endpoint in forbidden if endpoint in source]
        if matches:
            offenders[name] = matches
    assert offenders == {}


def test_truth_pages_use_canonical_sources_and_execution_lock() -> None:
    active = "\n".join(
        _text(name)
        for name in (
            "web2_shell_v44.js",
            "overview_runtime_v44.js",
            "canonical_pages_v45.js",
            "tradingview_market_v32.js",
            "ai_center_v44.js",
            "system_status_v44.js",
        )
    )
    assert "/api/system/runtime-truth" in active
    assert "/api/autonomous-paper/events" in active
    assert "CouncilAuthorizedPaperLoop" in active
    assert "real orders blocked" in active or "real_orders_blocked" in active
    assert "основных API" not in active
    assert "core APIs" not in active
    assert "9/9" not in active


def test_ui_separates_transport_availability_from_runtime_verdict() -> None:
    status = _text("system_status_v44.js")
    overview = _text("overview_runtime_v44.js")
    ai_center = _text("ai_center_v44.js")
    assert "только транспорт, не здоровье" in status
    assert "не равен доступности HTTP" in overview
    assert "HTTP-ответ не считается доказательством здоровья" in ai_center
