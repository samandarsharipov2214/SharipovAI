from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPORT_BACKUP = ROOT / "deploy" / "vps" / "export_backup.sh"


def _run_backup_probe(
    tmp_path: Path,
    *,
    fixed_container: bool = True,
    running: str = "true",
    runtime_service: str = "dashboard",
    runtime_mode: str = "production-safe",
    compose_service: str = "sharipovai",
    inspect_failure: str = "",
    inventory_failure: bool = False,
    volume_lookup_failure: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    backup_dir = tmp_path / "backups"
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    live_mount = tmp_path / "live-volume"
    live_mount.mkdir()
    (live_mount / "state.txt").write_text("live", encoding="utf-8")
    trace = tmp_path / "docker.trace"

    (mock_bin / "df").write_text(
        "#!/usr/bin/env bash\nprintf 'Filesystem 1B-blocks Used Available Use%% Mounted\\n/dev/mock 1 0 107374182400 0%% /\\n'\n",
        encoding="utf-8",
    )
    (mock_bin / "df").chmod(0o755)
    (mock_bin / "docker").write_text(
        r'''#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TRACE"
if [[ "${1:-}" == container && "${2:-}" == ls ]]; then
  [[ "$INVENTORY_FAILURE" == 1 ]] && exit 43
  [[ "$FIXED_CONTAINER" == 1 ]] && printf 'live-container\n'
  exit 0
fi
if [[ "${1:-}" == inspect && "${2:-}" == --format ]]; then
  case "${3:-}" in
    *'.Id'*) [[ "$INSPECT_FAILURE" == identity ]] && exit 44; printf 'canonical-live-container\n' ;;
    *ai.sharipov.service*) [[ "$INSPECT_FAILURE" == labels ]] && exit 45; printf '%s\n' "$RUNTIME_SERVICE" ;;
    *ai.sharipov.runtime-mode*) printf '%s\n' "$RUNTIME_MODE" ;;
    *com.docker.compose.service*) printf '%s\n' "$COMPOSE_SERVICE" ;;
    *State.Running*) [[ "$INSPECT_FAILURE" == state ]] && exit 46; printf '%s\n' "$RUNNING" ;;
    *Mounts*) [[ "$INSPECT_FAILURE" == volume ]] && exit 47; printf 'live-volume\n' ;;
    *Config.Image*) [[ "$INSPECT_FAILURE" == image ]] && exit 48; printf 'live-image\n' ;;
  esac
  exit 0
fi
if [[ "${1:-}" == compose && "${2:-}" == ps ]]; then
  [[ "$FIXED_CONTAINER" == 0 ]] && printf 'default-compose-container\n'
  exit 0
fi
if [[ "${1:-}" == compose && "${2:-}" == config ]]; then
  printf '%s\n' '{"services":{"sharipovai":{"image":"stale-image"}},"volumes":{"sharipovai_data":{"name":"stale-volume"}}}'
  exit 0
fi
if [[ "${1:-}" == volume && "${2:-}" == inspect ]]; then
  [[ "$VOLUME_LOOKUP_FAILURE" == 1 ]] && exit 49
  if [[ "${3:-}" == --format ]]; then printf '%s\n' "$LIVE_MOUNT"; fi
  exit 0
fi
if [[ "${1:-}" == image && "${2:-}" == inspect ]]; then exit 0; fi
if [[ "${1:-}" == run ]]; then exit 73; fi
if [[ "${1:-}" == rm ]]; then exit 0; fi
exit 97
''',
        encoding="utf-8",
    )
    (mock_bin / "docker").chmod(0o755)

    result = subprocess.run(
        ["bash", str(EXPORT_BACKUP)],
        text=True,
        capture_output=True,
        check=False,
        env=os.environ
        | {
            "APP_DIR": str(ROOT),
            "BACKUP_DIR": str(backup_dir),
            "COMPOSE_DIR": str(compose_dir),
            "COMPOSE_SERVICE": compose_service,
            "FIXED_CONTAINER": "1" if fixed_container else "0",
            "INSPECT_FAILURE": inspect_failure,
            "INVENTORY_FAILURE": "1" if inventory_failure else "0",
            "LIVE_MOUNT": str(live_mount),
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "RUNTIME_MODE": runtime_mode,
            "RUNTIME_SERVICE": runtime_service,
            "RUNNING": running,
            "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB": "1",
            "SHARIPOVAI_BACKUP_RESERVE_MIB": "0",
            "TRACE": str(trace),
            "VOLUME_LOOKUP_FAILURE": "1" if volume_lookup_failure else "0",
        },
    )
    return result, trace.read_text(encoding="utf-8")


@pytest.mark.parametrize("running", ["true", "false"])
def test_backup_uses_transactional_runtime_volume_for_running_or_stopped_container(
    tmp_path: Path, running: str
) -> None:
    result, calls = _run_backup_probe(tmp_path, running=running)

    assert result.returncode != 0
    expected = (
        "creating transactionally consistent backup"
        if running == "true"
        else "application container is stopped"
    )
    assert expected in result.stdout
    assert "container ls -a --no-trunc --filter name=^/sharipovai$" in calls
    assert "compose ps" not in calls
    assert "-v live-volume:/source:ro" in calls
    assert "stale-volume:/source:ro" not in calls


def test_backup_default_compose_runtime_remains_supported(tmp_path: Path) -> None:
    result, calls = _run_backup_probe(tmp_path, fixed_container=False)

    assert result.returncode != 0
    assert "compose ps -a -q sharipovai" in calls
    assert "-v live-volume:/source:ro" in calls


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"runtime_service": "wrong"}, "unexpected production identity"),
        ({"runtime_service": ""}, "unexpected production identity"),
        ({"runtime_mode": "wrong"}, "unexpected production identity"),
        ({"compose_service": "wrong"}, "unexpected production identity"),
        ({"inspect_failure": "identity"}, "could not inspect application container identity"),
        ({"inspect_failure": "labels"}, "could not inspect application service identity"),
        ({"inspect_failure": "state"}, "could not inspect application container state"),
        ({"inspect_failure": "volume"}, "could not inspect live persistent data volume"),
        ({"inspect_failure": "image"}, "could not inspect live application image"),
        ({"inventory_failure": True}, "could not inspect fixed-name application container inventory"),
        ({"volume_lookup_failure": True}, "persistent data volume is missing"),
    ],
)
def test_backup_runtime_probe_failures_never_fall_back_to_stale_volume(
    tmp_path: Path, overrides: dict[str, object], reason: str
) -> None:
    result, calls = _run_backup_probe(tmp_path, **overrides)

    assert result.returncode != 0
    assert reason in result.stderr
    assert "compose config" not in calls
    assert "stale-volume:/source:ro" not in calls
    assert "docker run" not in calls


def test_backup_fixed_runtime_identity_is_fail_closed() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert 'ai.sharipov.service' in source
    assert 'ai.sharipov.runtime-mode' in source
    assert 'com.docker.compose.service' in source
    assert "fail 'application container has an unexpected production identity'" in source
    assert "fail 'could not inspect live persistent data volume'" in source
