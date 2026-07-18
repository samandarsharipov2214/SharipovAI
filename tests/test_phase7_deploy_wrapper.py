from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy_web2_refresh_fix.sh"


def test_phase7_deploy_wrapper_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_phase7_deploy_wrapper_tracks_current_dashboard_assets() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for value in (
        "campaign_operations_v36.js",
        "campaign_decision_v37.js",
        "campaign_monitor_v38.js",
        "campaign_monitor_v38.css",
        "PHASE7_DASHBOARD_CONTRACTS_OK",
    ):
        assert value in source
