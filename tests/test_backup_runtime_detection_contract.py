from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_BACKUP = ROOT / "deploy" / "vps" / "export_backup.sh"


def test_backup_detects_transactional_runtime_by_fixed_identity(tmp_path: Path) -> None:
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
if [[ "${1:-}" == container && "${2:-}" == inspect ]]; then
  printf 'live-container\n'; exit 0
fi
if [[ "${1:-}" == inspect && "${2:-}" == --format ]]; then
  case "${3:-}" in
    *ai.sharipov.service*) printf 'dashboard\n' ;;
    *ai.sharipov.runtime-mode*) printf 'production-safe\n' ;;
    *com.docker.compose.service*) printf 'sharipovai\n' ;;
    *State.Running*) printf 'true\n' ;;
    *Mounts*) printf 'live-volume\n' ;;
    *Config.Image*) printf 'live-image\n' ;;
    *'.Id'*) exit 0 ;;
  esac
  exit 0
fi
if [[ "${1:-}" == compose && "${2:-}" == ps ]]; then exit 96; fi
if [[ "${1:-}" == compose && "${2:-}" == config ]]; then
  printf '%s\n' '{"services":{"sharipovai":{"image":"stale-image"}},"volumes":{"sharipovai_data":{"name":"stale-volume"}}}'
  exit 0
fi
if [[ "${1:-}" == volume && "${2:-}" == inspect ]]; then
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
            "LIVE_MOUNT": str(live_mount),
            "PATH": f"{mock_bin}:{os.environ['PATH']}",
            "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB": "1",
            "SHARIPOVAI_BACKUP_RESERVE_MIB": "0",
            "TRACE": str(trace),
        },
    )

    assert result.returncode != 0
    assert "creating transactionally consistent backup" in result.stdout
    calls = trace.read_text(encoding="utf-8")
    assert "container inspect --format {{.Id}} sharipovai" in calls
    assert "compose ps" not in calls
    assert "-v live-volume:/source:ro" in calls
    assert "stale-volume:/source:ro" not in calls


def test_backup_fixed_runtime_identity_is_fail_closed() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert 'ai.sharipov.service' in source
    assert 'ai.sharipov.runtime-mode' in source
    assert 'com.docker.compose.service' in source
    assert "fail 'fixed-name application container has an unexpected production identity'" in source
