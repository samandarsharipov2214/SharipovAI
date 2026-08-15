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
if [[ "$*" != 'builder prune -af' ]]; then exit 91; fi
if [[ "${FAKE_RECOVER_ON_PRUNE:-0}" == 1 ]]; then printf 'high' > "$FAKE_DF_STATE_FILE"; fi
exit "${FAKE_DOCKER_RC:-0}"
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
            "SHARIPOVAI_BUILD_CACHE_PRUNE_TIMEOUT_SECONDS": "15",
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


def test_preflight_does_nothing_when_headroom_is_already_safe(fake_runtime) -> None:
    env, state, docker_log = fake_runtime
    state.write_text("high", encoding="utf-8")
    result = _run("preflight", env)
    assert result.returncode == 0
    assert "STORAGE_GUARD_PREFLIGHT_OK" in result.stdout
    assert not docker_log.exists()


def test_preflight_recovers_low_disk_using_only_build_cache(fake_runtime) -> None:
    env, _state, docker_log = fake_runtime
    env["FAKE_RECOVER_ON_PRUNE"] = "1"
    result = _run("preflight", env)
    assert result.returncode == 0
    assert "STORAGE_GUARD_RECOVERED" in result.stdout
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["builder prune -af"]


def test_preflight_fails_closed_if_safe_cleanup_cannot_restore_headroom(fake_runtime) -> None:
    env, _state, docker_log = fake_runtime
    result = _run("preflight", env)
    assert result.returncode == 70
    assert "STORAGE_GUARD_PREFLIGHT_FAILED" in result.stderr
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["builder prune -af"]


def test_post_deploy_cleanup_is_best_effort_and_prunes_build_cache(fake_runtime) -> None:
    env, state, docker_log = fake_runtime
    state.write_text("high", encoding="utf-8")
    env["FAKE_DOCKER_RC"] = "9"
    result = _run("cleanup", env)
    assert result.returncode == 0
    assert "STORAGE_GUARD_POST_DEPLOY_CLEANUP_WARNING" in result.stderr
    assert docker_log.read_text(encoding="utf-8").splitlines() == ["builder prune -af"]


def test_storage_guard_never_invokes_broad_docker_prune_classes() -> None:
    text = GUARD.read_text(encoding="utf-8")
    assert "docker builder prune -af" in text
    for forbidden in (
        "docker system prune",
        "docker volume prune",
        "docker image prune",
        "docker container prune",
        "docker buildx prune",
        "docker rmi",
    ):
        assert forbidden not in text


def test_transactional_web2_deploy_runs_preflight_and_exit_cleanup() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert 'bash "$STORAGE_GUARD" preflight' in text
    assert 'bash "$STORAGE_GUARD" cleanup || true' in text
    assert "trap post_deploy_storage_cleanup EXIT" in text
    assert text.index('bash "$STORAGE_GUARD" preflight') < text.index("deploy_market_paper_runtime.sh")


def test_guard_has_required_host_tools() -> None:
    if shutil.which("bash") is None or shutil.which("timeout") is None:
        pytest.skip("Linux shell tools are required for deploy guard tests")
