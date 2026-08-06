from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def _text(name: str) -> str:
    return (WEB2 / name).read_text(encoding="utf-8")


def test_web2_loads_only_canonical_truth_page_owners() -> None:
    index = _text("index.html")

    for script in (
        "navigation_coordinator_v44.js",
        "web2_shell_v44.js",
        "overview_runtime_v44.js",
        "ai_center_v44.js",
        "system_status_v44.js",
    ):
        assert script in index

    for legacy in (
        "navigation_coordinator_v23.js",
        "web2.js?v=44",
        "canonical_runtime_ui_v44.js",
        "overview_runtime_v25.js",
        "system_status_v11.js",
        "ai_center_v14.js",
    ):
        assert legacy not in index


def test_navigation_coordinator_assigns_one_owner_per_truth_page() -> None:
    coordinator = _text("navigation_coordinator_v44.js")

    assert "['overview', 'overview_runtime_v44.js']" in coordinator
    assert "['bots', 'ai_center_v44.js']" in coordinator
    assert "['system-status', 'system_status_v44.js']" in coordinator
    assert "['chat', 'web2_shell_v44.js']" in coordinator


def test_active_ui_does_not_call_legacy_runtime_endpoints() -> None:
    active_sources = "\n".join(
        _text(name)
        for name in (
            "web2_shell_v44.js",
            "overview_runtime_v44.js",
            "ai_center_v44.js",
            "system_status_v44.js",
        )
    )

    assert "/api/run" not in active_sources
    assert "/api/ai-bots" not in active_sources
    assert "/api/virtual-account/state" not in active_sources
    assert "/api/system/runtime-truth" in active_sources
    assert "CouncilAuthorizedPaperLoop" in active_sources


def test_ui_separates_transport_availability_from_runtime_verdict() -> None:
    shell = _text("web2_shell_v44.js")
    status = _text("system_status_v44.js")
    overview = _text("overview_runtime_v44.js")

    assert "основных API" not in shell
    assert "core APIs" not in shell
    assert "9/9" not in shell + status + overview
    assert "только транспорт, не здоровье" in status
    assert "не равен доступности HTTP" in overview
    assert "HTTP-ответ не считается доказательством здоровья" in _text("ai_center_v44.js")


def test_ui_names_canonical_owners_and_execution_lock() -> None:
    source = _text("overview_runtime_v44.js") + _text("web2_shell_v44.js")

    assert "CouncilAuthorizedPaperLoop" in source
    assert "RiskService" in source
    assert "real orders blocked" in source
    assert "Legacy PaperActivityEngine не используется" in source
