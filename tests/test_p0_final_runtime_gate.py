from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_final_p0_ui_gate_has_one_truth_endpoint_and_no_legacy_consumers() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    active = "\n".join(
        (WEB2 / name).read_text(encoding="utf-8")
        for name in (
            "web2_shell_v44.js",
            "overview_runtime_v44.js",
            "ai_center_v44.js",
            "system_status_v44.js",
        )
    )

    assert "navigation_coordinator_v44.js" in index
    assert "/api/system/runtime-truth" in active
    assert "/api/run" not in active
    assert "/api/ai-bots" not in active
    assert "/api/virtual-account/state" not in active
    assert "overview_runtime_v25.js" not in index
    assert "ai_center_v14.js" not in index
    assert "system_status_v11.js" not in index


def test_final_p0_backend_gate_names_owners_and_blocks_legacy_mutation() -> None:
    source = (ROOT / "dashboard" / "canonical_runtime_compat_api.py").read_text(encoding="utf-8")

    assert '"paper": "CouncilAuthorizedPaperLoop"' in source
    assert '"risk": "risk_engine.canonical_service"' in source
    assert '"organs": "AIOrganRuntimeMonitor"' in source
    assert '"database": "ProjectDatabase"' in source
    assert '"api_run_allowed_for_ui": False' in source
    assert '"paper_activity_engine_active": False' in source
    assert "status_code=410" in source
    assert '"automatic_legacy_mutation": False' in source
