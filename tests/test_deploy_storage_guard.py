from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "deploy_storage_guard.sh"
WRAPPER = ROOT / "scripts" / "deploy_web2_refresh_fix.sh"


@pytest.fixture
def fake_runtime(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    deploy_root = tmp_path / "repo"
    deploy_root.mkdir()
    state = tmp_path / "df-state"
    state.write_text("low", encoding="utf-8")
    docker_log = tmp_path / "docker.log"

    (fake_bin / "df").write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
state=$(cat "$FAKE_DF_STATE_FILE")
if [[ "$state" == high ]]; then avail=26214400; else avail=8388608; fi
if [[ "${1:-}" == -Pk ]]; then
  printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'
  printf '/dev/fake 62914560 1 %s 50%% /\\n' "$avail"
else
  printf '/dev/fake 60G 1G 25G 50%% /\\n'
fi
""",
        encoding="utf-8",
    )
    (fake_bin / "docker").write_text(
        """#!/usr/bin/env bash
set -Eeuo pipefail
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
if [[ "$*" == 'system df' ]]; then
  printf 'TYPE TOTAL ACTIVE SIZE RECLAIMABLE\\n'
  exit 0
fi
exit 91
""",
        encoding="utf-8",
    )
    for path in (fake_bin / "df", fake_bin / "docker"):
        path.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "SHARIPOVAI_DEPLOY_ROOT": str(deploy_root),
            "SHARIPOVAI_DEPLOY_MIN_FREE_DISK_GB": "20",
            "FAKE_DF_STATE_FILE": str(state),
            "FAKE_DOCKER_LOG": str(docker_log),
        }
    )
    return env, state, docker_log


def _run(mode: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD), mode],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_is_read_only_when_headroom_is_already_safe(fake_runtime) -> None:
    env, state, docker_log = fake_runtime
    state.write_text("high", encoding="utf-8")
    result = _run("preflight", env)
    assert result.returncode == 0
    assert "STORAGE_GUARD_EVIDENCE_UTC" in result.stdout
    assert "STORAGE_GUARD_PREFLIGHT_OK" in result.stdout
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["system df"]


def test_preflight_fails_closed_on_low_disk_without_pruning(fake_runtime) -> None:
    env, _state, docker_log = fake_runtime
    result = _run("preflight", env)
    assert result.returncode == 70
    assert "STORAGE_GUARD_PRESSURE" in result.stderr
    assert "automatic cleanup is disabled" in result.stderr
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["system df"]


def test_cleanup_mode_is_read_only_and_skips_automatic_cleanup(fake_runtime) -> None:
    env, state, docker_log = fake_runtime
    state.write_text("high", encoding="utf-8")
    result = _run("cleanup", env)
    assert result.returncode == 0
    assert "STORAGE_GUARD_EVIDENCE_UTC" in result.stdout
    assert "STORAGE_GUARD_CLEANUP_SKIPPED" in result.stdout
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["system df"]


def test_storage_guard_never_invokes_docker_prune_or_delete_classes() -> None:
    text = GUARD.read_text(encoding="utf-8")
    for forbidden in (
        "docker builder prune",
        "docker system prune",
        "docker volume prune",
        "docker image prune",
        "docker container prune",
        "docker buildx prune",
        "docker rmi",
        "docker rm",
    ):
        assert forbidden not in text


def test_transactional_web2_deploy_runs_preflight_and_exit_cleanup() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert 'bash "$STORAGE_GUARD" preflight' in text
    assert 'bash "$STORAGE_GUARD" cleanup || true' in text
    assert "trap post_deploy_storage_cleanup EXIT" in text
    assert text.index('bash "$STORAGE_GUARD" preflight') < text.index("deploy_market_paper_runtime.sh")


def test_guard_has_required_host_tools() -> None:
    if shutil.which("bash") is None:
        pytest.skip("Linux shell tools are required for deploy guard tests")
