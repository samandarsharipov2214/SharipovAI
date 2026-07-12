from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "deploy" / "vps" / "verify_production.sh"


def text() -> str:
    return VERIFY.read_text(encoding="utf-8")


def test_verifier_shell_syntax_when_bash_is_available() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available on this test worker")
    result = subprocess.run(
        [bash, "-n", str(VERIFY)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_verifier_is_read_only_and_cannot_change_runtime() -> None:
    content = text()
    forbidden = (
        "docker compose up",
        "docker compose build",
        "docker compose down",
        "docker restart",
        "systemctl restart",
        "systemctl start",
        "systemctl stop",
        "git reset",
        "git checkout",
        "git pull",
        "--request POST",
        "--method POST",
        "-X POST",
    )
    for fragment in forbidden:
        assert fragment not in content


def test_verifier_confirms_exact_main_commit_without_mutating_checkout() -> None:
    content = text()
    assert 'git -C "${APP_DIR}" fetch --quiet origin main' in content
    assert 'git -C "${APP_DIR}" rev-parse HEAD' in content
    assert 'git -C "${APP_DIR}" rev-parse "${ORIGIN_REF}"' in content
    assert 'current_branch="$(git -C "${APP_DIR}" symbolic-ref --short HEAD' in content
    assert "checkout matches ${ORIGIN_REF}" in content


def test_verifier_checks_financial_locks_fail_closed() -> None:
    content = text()
    assert '"EXCHANGE_LIVE_TRADING_ENABLED": "0"' in content
    assert '"EXECUTION_KILL_SWITCH": "1"' in content
    for flag in (
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        "TESTNET_EXECUTION_ENABLED",
        "FEATURE_BYBIT_TESTNET",
        "FEATURE_BYBIT_LIVE_EXECUTION",
    ):
        assert flag in content
    assert "rendered compose contains unsafe financial settings" in content


def test_verifier_checks_containers_health_and_canonical_runtime() -> None:
    content = text()
    assert "container_state sharipovai" in content
    assert "container_state sharipovai-caddy" in content
    assert '"${LOCAL_BASE_URL}/health"' in content
    assert '"${LOCAL_BASE_URL}/api/system/health"' in content
    assert '"${LOCAL_BASE_URL}/api/autonomous-paper/decision-runtime"' in content
    assert '"${LOCAL_BASE_URL}/api/autonomous-paper/status"' in content
    assert 'payload.get("decision_mode") == "CANONICAL_COUNCIL_REQUIRED"' in content
    assert 'payload.get("entry_without_authorization_allowed") is False' in content
    assert 'payload.get("synthetic_fallback_used") is False' in content


def test_verifier_checks_backup_integrity_age_and_runner_online() -> None:
    content = text()
    assert "latest.tar.gz" in content
    assert "latest.tar.gz.sha256" in content
    assert "sha256sum -c" in content
    assert "MAX_BACKUP_AGE_HOURS" in content
    assert "actions.runner" in content
    assert "systemctl is-enabled" in content
    assert "systemctl is-active" in content
    assert "SHARIPOVAI_SELF_HOSTED_CI" in content
    assert '"sharipovai-ci" in labels' in content
    assert "runner.get(\"status\"" in content


def test_verifier_writes_machine_readable_report_without_secrets() -> None:
    content = text()
    assert "sharipovai-production-verification.json" in content
    assert '"overall_status"' in content
    assert '"local_commit"' in content
    assert '"target_commit"' in content
    assert '"checks"' in content
    assert "VERIFY_SESSION_COOKIE" not in content.split("python3 - \"${records_file}\"")[1]
    assert 'chmod 0644 "${REPORT_JSON}"' in content
    assert "exit 2" in content
