from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
UPDATE = ROOT / "deploy" / "vps" / "update_from_main.sh"
INSTALL = ROOT / "deploy" / "vps" / "install.sh"
EXPORT = ROOT / "deploy" / "vps" / "export_backup.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_vps_shell_scripts_parse_when_bash_is_available() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not available on this test worker")
    for path in (UPDATE, INSTALL, EXPORT):
        result = subprocess.run(
            [bash, "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"


def test_all_vps_scripts_use_the_real_repository_path() -> None:
    for path in (UPDATE, INSTALL, EXPORT):
        content = _text(path)
        assert "/opt/sharipovai-repo" in content
        assert "APP_DIR=${APP_DIR:-/opt/sharipovai}" not in content
        assert 'APP_DIR="${APP_DIR:-/opt/sharipovai}"' not in content


def test_update_is_locked_backup_first_and_never_cleans_runtime_files() -> None:
    content = _text(UPDATE)
    assert "flock -n 9" in content
    assert "creating verified backup before code update" in content
    assert 'bash "${backup_exporter}"' in content
    assert "git -C \"${APP_DIR}\" reset --hard \"${target_sha}\"" in content
    assert content.index("creating verified backup before code update") < content.index(
        'reset --hard "${target_sha}"'
    )
    assert "git clean" not in content


def test_update_can_bootstrap_backup_exporter_without_mutating_checkout() -> None:
    content = _text(UPDATE)
    assert 'git -C "${APP_DIR}" fetch --prune origin "${BRANCH}"' in content
    assert 'show "origin/${BRANCH}:deploy/vps/export_backup.sh"' in content
    assert content.index('fetch --prune origin "${BRANCH}"') < content.index(
        "creating verified backup before code update"
    )
    assert content.index("creating verified backup before code update") < content.index(
        'checkout -q "${BRANCH}"'
    )


def test_update_validates_financial_locks_before_build_and_rollback() -> None:
    content = _text(UPDATE)
    assert '"EXCHANGE_LIVE_TRADING_ENABLED": "0"' in content
    assert '"EXECUTION_KILL_SWITCH": "1"' in content
    for flag in (
        "AUTONOMOUS_TESTNET_BRIDGE_ENABLED",
        "TESTNET_EXECUTION_ENABLED",
        "FEATURE_BYBIT_TESTNET",
        "FEATURE_BYBIT_LIVE_EXECUTION",
    ):
        assert flag in content
    assert content.count("validate_financial_locks") >= 3
    assert content.index('validate_financial_locks "${rendered_config}"') < content.index(
        "docker compose build --pull"
    )


def test_update_rolls_back_exact_commit_and_requires_health() -> None:
    content = _text(UPDATE)
    assert 'previous_sha="$(git -C "${APP_DIR}" rev-parse HEAD)"' in content
    assert 'reset --hard "${previous_sha}"' in content
    assert "health_check || rollback" in content
    assert "rollback container did not become healthy" in content
    assert "docker inspect --format" in content


def test_repeat_install_delegates_to_target_branch_updater() -> None:
    content = _text(INSTALL)
    assert 'show "origin/${BRANCH}:deploy/vps/update_from_main.sh"' in content
    assert 'APP_DIR="${APP_DIR}" BRANCH="${BRANCH}" bash "${updater}"' in content
    existing_repo = content.index('if [[ -d "${APP_DIR}/.git" ]]')
    direct_clone = content.index('git clone --branch "${BRANCH}"')
    assert existing_repo < direct_clone


def test_initial_install_keeps_live_locked() -> None:
    content = _text(INSTALL)
    assert "live trading must be disabled" in content
    assert "execution kill switch must be enabled" in content
    assert content.index("docker compose config --format json") < content.index(
        "docker compose build --pull"
    )
