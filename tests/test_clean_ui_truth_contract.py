from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def _text(name: str) -> str:
    return (WEB2 / name).read_text(encoding="utf-8")


def test_web2_loads_single_canonical_truth_renderer() -> None:
    index = _text("index.html")

    assert "canonical_runtime_ui_v44.js" in index
    assert "overview_runtime_v25.js" not in index
    assert "system_status_v11.js" not in index
    assert "ai_center_v14.js" not in index


def test_active_ui_does_not_call_legacy_runtime_endpoints() -> None:
    active_sources = _text("web2.js") + _text("canonical_runtime_ui_v44.js")

    assert "/api/run" not in active_sources
    assert "/api/ai-bots" not in active_sources
    assert "/api/virtual-account/state" not in active_sources
    assert "/api/system/health" in active_sources
    assert "/api/system/ai-organs" in active_sources
    assert "/api/autonomous-paper/status" in active_sources
    assert "/api/autonomous-paper/decision-runtime" in active_sources


def test_ui_reports_verdicts_instead_of_false_endpoint_scoreboard() -> None:
    source = _text("canonical_runtime_ui_v44.js") + _text("web2.js")

    assert "основных API" not in source
    assert "core APIs" not in source
    assert "ИИ онлайн" not in source
    assert "counts.healthy" in source
    assert "counts.degraded" in source
    assert "counts.blocked" in source
    assert "не подменяется формулой 9/9" in source
    assert "Девять зарегистрированных органов — это реестр архитектуры" in source


def test_ui_names_the_canonical_execution_owner() -> None:
    source = _text("canonical_runtime_ui_v44.js")

    assert "CouncilAuthorizedPaperLoop" in source
    assert "CANONICAL_COUNCIL_REQUIRED" in source
    assert "Legacy PaperActivityEngine" in source
    assert "real_execution_enabled" in source
