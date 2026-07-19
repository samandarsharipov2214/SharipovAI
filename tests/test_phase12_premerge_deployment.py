from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.phase12_premerge_checklist import run_checklist

ROOT = Path(__file__).resolve().parents[1]


def test_phase12_premerge_checklist_passes_clean_source_snapshot() -> None:
    report = run_checklist(ROOT, allow_no_git=True)
    assert report["status"] == "ready_for_merge"
    assert report["blockers"] == []
    assert report["mainnet_enabled"] is False
    assert report["automatic_execution_promotion"] is False
    assert len(report["evidence_sha256"]) == 64


def test_phase12_deployment_scripts_have_valid_syntax_and_exact_sha_contracts() -> None:
    scripts = [
        ROOT / "deploy" / "vps" / "phase12_release_preflight.sh",
        ROOT / "deploy" / "vps" / "phase12_post_deploy_verify.sh",
        ROOT / "deploy" / "vps" / "phase12_rollback.sh",
    ]
    for script in scripts:
        subprocess.run(["bash", "-n", str(script)], check=True)
        source = script.read_text(encoding="utf-8")
        assert "SHARIPOVAI_EXPECTED_SHA" in source
        assert "40" in source or "{40}" in source
    assert "phase11_release_preflight.sh" in scripts[0].read_text(encoding="utf-8")
    assert "phase11_post_deploy_verify.sh" in scripts[1].read_text(encoding="utf-8")
    assert "phase11_rollback.sh" in scripts[2].read_text(encoding="utf-8")
    assert "merge-base --is-ancestor" in scripts[2].read_text(encoding="utf-8")


def test_phase12_dashboard_and_compose_integrate_supervisor_without_execution_authority() -> None:
    api = (ROOT / "dashboard" / "self_learning_api.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "dashboard" / "__init__.py").read_text(encoding="utf-8")
    guard = (ROOT / "dashboard" / "admin_guard.py").read_text(encoding="utf-8")
    compose = (ROOT / "deploy" / "vps" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "install_self_learning_api" in bootstrap
    assert "/api/learning/phase12/" in guard
    assert "require_admin(request)" in api
    assert '"execution_authority": False' in api
    assert '"automatic_execution_promotion": False' in api
    assert 'SELF_LEARNING_ENABLED: "1"' in compose
    assert 'EXECUTION_KILL_SWITCH: "1"' in compose
    assert 'EXCHANGE_LIVE_TRADING_ENABLED: "0"' in compose
    assert 'TESTNET_EXECUTION_ENABLED: "0"' in compose
