from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DEPLOY = ROOT / "scripts" / "deploy_market_paper_runtime.sh"
EXPORT_BACKUP = ROOT / "deploy" / "vps" / "export_backup.sh"


def _run_runtime_with_evidence_failure(tmp_path: Path, *, fail: str) -> subprocess.CompletedProcess[str]:
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    build_trace = tmp_path / "build-trace.txt"

    df_mock = mock_bin / "df"
    df_mock.write_text(
        """#!/usr/bin/env bash
if [[ "${FAIL_EVIDENCE:-}" == "df" && "${1:-}" == "-h" ]]; then
  exit 42
fi
cat <<'EOF'
Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/mock 104857600 0 104857600 0% /
EOF
""",
        encoding="utf-8",
    )
    df_mock.chmod(0o755)

    docker_mock = mock_bin / "docker"
    docker_mock.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "container" && "${2:-}" == "inspect" ]]; then
  exit 1
fi
if [[ "${1:-}" == "system" && "${2:-}" == "df" ]]; then
  if [[ "${FAIL_EVIDENCE:-}" == "docker" ]]; then
    exit 43
  fi
  printf 'TYPE TOTAL ACTIVE SIZE RECLAIMABLE\\n'
  exit 0
fi
if [[ "${1:-}" == "compose" && "${2:-}" == "build" ]]; then
  printf 'build reached\\n' >"${BUILD_TRACE}"
  exit 73
fi
echo "unexpected docker invocation: $*" >&2
exit 74
""",
        encoding="utf-8",
    )
    docker_mock.chmod(0o755)

    environment = os.environ | {
        "BUILD_TRACE": str(build_trace),
        "FAIL_EVIDENCE": fail,
        "PATH": f"{mock_bin}:{os.environ['PATH']}",
        "SHARIPOVAI_DEPLOY_ROOT": str(ROOT),
    }
    result = subprocess.run(
        ["bash", str(RUNTIME_DEPLOY)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    assert not build_trace.exists(), "candidate build must not run without fresh disk evidence"
    return result


def test_runtime_aborts_before_build_when_host_disk_evidence_fails(tmp_path: Path) -> None:
    result = _run_runtime_with_evidence_failure(tmp_path, fail="df")

    assert result.returncode == 42
    assert "Candidate verification failed before production replacement" in result.stdout
    assert "DEPLOY_DISK_PREFLIGHT_OK" not in result.stdout


def test_runtime_aborts_before_build_when_docker_disk_evidence_fails(tmp_path: Path) -> None:
    result = _run_runtime_with_evidence_failure(tmp_path, fail="docker")

    assert result.returncode == 43
    assert "Candidate verification failed before production replacement" in result.stdout
    assert "DEPLOY_DISK_PREFLIGHT_OK" not in result.stdout


def test_runtime_uses_same_fail_closed_evidence_function_before_build_and_backup() -> None:
    source = RUNTIME_DEPLOY.read_text(encoding="utf-8")

    assert source.count('fresh_disk_evidence "before-candidate-build"') == 1
    assert source.count('fresh_disk_evidence "before-canonical-backup"') == 1
    function = source[source.index("fresh_disk_evidence() {") : source.index("head_sha=", source.index("fresh_disk_evidence() {"))]
    assert 'df -h "$ROOT" >&2' in function
    assert "docker system df >&2" in function
    assert "|| true" not in function


def test_export_backup_reads_live_volume_not_stale_default(tmp_path: Path) -> None:
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    backup_dir = tmp_path / "backups"
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    live_mount = tmp_path / "live-volume-mount"
    live_mount.mkdir()
    (live_mount / "state.txt").write_text("live", encoding="utf-8")
    trace = tmp_path / "docker-trace.txt"

    df_mock = mock_bin / "df"
    df_mock.write_text(
        """#!/usr/bin/env bash
cat <<'EOF'
Filesystem 1B-blocks Used Available Use% Mounted on
/dev/mock 107374182400 0 107374182400 0% /
EOF
""",
        encoding="utf-8",
    )
    df_mock.chmod(0o755)

    docker_mock = mock_bin / "docker"
    docker_mock.write_text(
        """#!/usr/bin/env bash
printf '%s project=%s\\n' "$*" "${COMPOSE_PROJECT_NAME:-}" >>"${TRACE}"
if [[ "${1:-}" == "compose" && "${2:-}" == "ps" ]]; then
  [[ "${COMPOSE_PROJECT_NAME:-}" == "live-project" ]] || exit 0
  printf 'live-container\\n'
  exit 0
fi
if [[ "${1:-}" == "compose" && "${2:-}" == "config" ]]; then
  cat <<'EOF'
{"services":{"sharipovai":{"image":"live-image"}},"volumes":{"sharipovai_data":{"name":"stale-default-volume"}}}
EOF
  exit 0
fi
if [[ "${1:-}" == "inspect" && "${2:-}" == "--format" ]]; then
  case "${3:-}" in
    *State.Running*) printf 'true\\n' ;;
    *Mounts*) printf 'live-volume\\n' ;;
    *Config.Image*) printf 'live-image\\n' ;;
    *Config.Labels*) exit 0 ;;
    *'.Id'*) exit 0 ;;
    *) exit 0 ;;
  esac
  exit 0
fi
if [[ "${1:-}" == "volume" && "${2:-}" == "inspect" ]]; then
  if [[ "${3:-}" == "--format" ]]; then
    [[ "${5:-}" == "live-volume" ]] || exit 91
    printf '%s\\n' "${LIVE_MOUNT}"
    exit 0
  fi
  [[ "${3:-}" == "live-volume" ]] || exit 92
  exit 0
fi
if [[ "${1:-}" == "image" && "${2:-}" == "inspect" ]]; then
  [[ "${3:-}" == "live-image" ]] || exit 93
  exit 0
fi
if [[ "${1:-}" == "run" ]]; then
  printf 'helper-volume-args=%s\\n' "$*" >>"${TRACE}"
  exit 73
fi
if [[ "${1:-}" == "rm" ]]; then
  exit 0
fi
echo "unexpected docker invocation: $*" >&2
exit 94
""",
        encoding="utf-8",
    )
    docker_mock.chmod(0o755)

    environment = os.environ | {
        "APP_DIR": str(ROOT),
        "BACKUP_DIR": str(backup_dir),
        "COMPOSE_DIR": str(compose_dir),
        "COMPOSE_PROJECT_NAME": "live-project",
        "CONTAINER": "sharipovai",
        "LIVE_MOUNT": str(live_mount),
        "PATH": f"{mock_bin}:{os.environ['PATH']}",
        "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB": "1",
        "SHARIPOVAI_BACKUP_RESERVE_MIB": "0",
        "TRACE": str(trace),
    }
    result = subprocess.run(
        ["bash", str(EXPORT_BACKUP)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode != 0, "mock helper intentionally stops the export after source selection"
    recorded = trace.read_text(encoding="utf-8")
    assert "compose ps -a -q sharipovai project=live-project" in recorded
    assert "-v live-volume:/source:ro" in recorded
    assert "-v stale-default-volume:/source:ro" not in recorded
