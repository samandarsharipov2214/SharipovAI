from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "deploy" / "vps" / "self-healing-run.sh"
HELPER = ROOT / "deploy" / "vps" / "self-healing-approved-patch.sh"


def _text() -> str:
    return WRAPPER.read_text(encoding="utf-8") + "\n" + HELPER.read_text(encoding="utf-8")


def test_wrapper_shell_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is unavailable")
    for script in (WRAPPER, HELPER):
        result = subprocess.run([bash, "-n", str(script)], text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


def test_apply_approved_patch_manifest_and_integrity_contract() -> None:
    text = _text()
    assert "apply_approved_patch)" in text
    for field in ("decision_id", "base_sha", "patch_sha256", "patch_container_path"):
        assert field in text
    assert "git rev-parse HEAD" in text
    assert "git status --porcelain" in text
    assert 'sha256sum "$patch_dir/candidate.patch"' in text
    assert "git apply --check --whitespace=error" in text
    assert "git apply --index --whitespace=error" in text


def test_security_guard_is_repeated_in_read_only_docker() -> None:
    text = _text()
    assert '-v "$REPO_DIR:/workspace:ro"' in text
    assert '-v "$patch_dir:/patches:ro"' in text
    assert '"$PATCH_VERIFY_IMAGE"' in text
    assert "python -m development_control.patch_policy --verify /patches/candidate.patch" in text


def test_targeted_and_full_regression_tests_are_both_required() -> None:
    text = _text()
    assert "discover_targeted_tests" in text
    assert 'run_patch_tests "$PATCH_TEST_TIMEOUT_SECONDS"' in text
    assert 'run_patch_tests "$PATCH_REGRESSION_TIMEOUT_SECONDS"' in text
    assert "EXECUTION_KILL_SWITCH=1" in text
    assert "TESTNET_EXECUTION_ENABLED=0" in text
    assert "EXCHANGE_LIVE_TRADING_ENABLED=0" in text


def test_commit_deploy_health_and_exact_revert_contract() -> None:
    text = _text()
    assert 'commit -m "[self-healing] fix $decision_id"' in text
    assert "compose build sharipovai" in text
    assert "compose up -d sharipovai caddy" in text
    assert "wait_for_health" in text
    assert 'revert_automatic_commit "$commit_sha"' in text
    assert 'git revert --no-edit "$expected_sha"' in text
    assert "git reset --hard" not in text
    assert "git clean -fd" not in text


def test_agent_decisions_api_is_fail_closed_audit_boundary() -> None:
    text = _text()
    assert "/internal/agent-decisions" in text
    assert "X-SharipovAI-Service-Token" in text
    assert "agent_decisions result persistence failed" in text
    assert "rollback_failed" in text
    assert "failed_precommit" in text
