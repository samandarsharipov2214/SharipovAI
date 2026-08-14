from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_web2_refresh_fix.sh"
VERIFY = ROOT / "scripts" / "verify_web2_refresh_contracts.sh"


def test_phase7_deploy_wrapper_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    subprocess.run(["bash", "-n", str(VERIFY)], check=True)


def test_phase7_deploy_wrapper_delegates_current_dashboard_contracts() -> None:
    wrapper = SCRIPT.read_text(encoding="utf-8")
    verifier = VERIFY.read_text(encoding="utf-8")

    assert "SHARIPOVAI_DEPLOY_PROFILE=web2-refresh" in wrapper
    assert "deploy_market_paper_runtime.sh" in wrapper
    assert "verify_web2_refresh_contracts.sh" not in wrapper

    for family in (
        "campaign_operations_v",
        "campaign_decision_v",
        "campaign_monitor_v",
    ):
        assert family in verifier
    assert "PHASE7_DASHBOARD_CONTRACTS_OK" in verifier
    assert "navigation_coordinator_v23.js" not in verifier
