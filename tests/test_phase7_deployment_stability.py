from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "deploy" / "vps" / "phase7_preflight.sh"
UPDATER = ROOT / "deploy" / "vps" / "update_from_main.sh"
COMPOSE = ROOT / "deploy" / "vps" / "docker-compose.yml"


def test_phase7_deployment_scripts_have_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(PREFLIGHT)], check=True)
    subprocess.run(["bash", "-n", str(UPDATER)], check=True)


def test_preflight_runs_before_backup_and_code_replacement() -> None:
    updater = UPDATER.read_text(encoding="utf-8")
    preflight = PREFLIGHT.read_text(encoding="utf-8")

    assert updater.index("running immutable target Phase 7 deployment preflight") < updater.index(
        "creating verified backup before code update"
    ) < updater.index("updating ${previous_sha} -> ${target_sha}")
    assert "PHASE7_COMPOSE_FILE" in updater
    assert 'show "${target_sha}:deploy/vps/docker-compose.yml"' in updater
    assert 'show "${target_sha}:deploy/vps/export_backup.sh"' in updater
    assert "PRAGMA quick_check" in preflight
    assert "COMPOSE_FILE" in preflight
    assert "MIN_FREE_MIB" in preflight
    assert "PREFLIGHT_OK" in preflight
    assert "PHASE7_PREFLIGHT_REPORT" in preflight


def test_compose_has_stable_restart_health_and_log_contracts() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")

    assert compose.count("init: true") == 2
    assert "stop_grace_period: 30s" in compose
    assert "PHASE7_CAMPAIGN_MONITOR_ENABLED" in compose
    assert "PHASE7_MONITOR_INTERVAL_SECONDS" in compose
    assert 'max-size: "20m"' in compose
    assert 'max-file: "5"' in compose
    assert "interval: 10s" in compose
    assert "restart: unless-stopped" in compose
