from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB2 = ROOT / "dashboard" / "static" / "web2"


def test_final_p0_ui_gate_has_one_truth_contract_and_no_loaded_legacy_consumers() -> None:
    index = (WEB2 / "index.html").read_text(encoding="utf-8")
    loaded = re.findall(r'<script[^>]+src="/static/web2/([^"?]+)', index)
    assert "navigation_coordinator_v44.js" in loaded
    assert "canonical_pages_v45.js" in loaded
    combined = "\n".join((WEB2 / name).read_text(encoding="utf-8") for name in loaded)
    assert "/api/system/runtime-truth" in combined
    for endpoint in (
        "/api/run",
        "/api/ai-bots",
        "/api/virtual-account/state",
        "/api/virtual-account/trades",
    ):
        assert endpoint not in combined
    for legacy in (
        "overview_runtime_v25.js",
        "decision_runtime_v25.js",
        "ai_center_v14.js",
        "system_status_v11.js",
        "general_control_v15.js",
        "portfolio_risk_v16.js",
        "learning_runtime_v25.js",
        "learning_evidence_reports_v17.js",
        "exchange_execution_settings_v18.js",
    ):
        assert legacy not in index


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
