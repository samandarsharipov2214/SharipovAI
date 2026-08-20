from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web2_verifier_waits_out_one_transient_telegram_cutover_error() -> None:
    script = (ROOT / "scripts" / "verify_web2_refresh_contracts.sh").read_text(encoding="utf-8")

    # Normal Telegram health remains conservative; only the transactional
    # cutover verifier receives the shorter bounded grace period.
    assert "TELEGRAM_WEBHOOK_ERROR_MAX_AGE_SECONDS=30" in script
    assert "for _ in range(30):" in script
    assert 'pending_updates = int(info.get("pending_update_count") or 0)' in script
    assert "and pending_updates == 0" in script
    assert "and not health.get(\"last_error_is_current\")" in script

    # The verifier must still fail closed: it may only pass once the same
    # Telegram health contract reports working after the quiet period.
    assert 'health.get("verdict") == "working"' in script
    assert 'raise AssertionError(f"Telegram webhook/menu verification failed: {last_evidence}")' in script


def test_storage_guard_uses_ephemeral_writable_docker_config(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "docker-config-path.txt"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
set -eu
[ "$#" -eq 3 ]
[ "$1" = "builder" ]
[ "$2" = "prune" ]
[ "$3" = "-af" ]
case "${DOCKER_CONFIG:-}" in
  /tmp/sharipovai-storage-guard-docker-config-*) ;;
  *) echo "unexpected DOCKER_CONFIG=${DOCKER_CONFIG:-missing}" >&2; exit 91 ;;
esac
[ -d "$DOCKER_CONFIG" ]
[ -w "$DOCKER_CONFIG" ]
printf '%s' "$DOCKER_CONFIG" > "$RECORD_FILE"
""",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env.get('PATH', '/usr/bin:/bin')}",
            "RECORD_FILE": str(record),
            "SHARIPOVAI_DEPLOY_ROOT": str(tmp_path),
            "SHARIPOVAI_BUILD_CACHE_PRUNE_TIMEOUT_SECONDS": "5",
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "deploy_storage_guard.sh"), "cleanup"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "STORAGE_GUARD_POST_DEPLOY_CLEANUP_OK" in result.stdout
    docker_config = Path(record.read_text(encoding="utf-8"))
    assert not docker_config.exists(), "temporary Docker client config leaked after prune"


def test_storage_guard_never_broad_prunes_images_or_volumes() -> None:
    script = (ROOT / "scripts" / "deploy_storage_guard.sh").read_text(encoding="utf-8")
    assert "docker builder prune -af" in script
    assert "docker system prune" not in script
    assert "docker image prune" not in script
    assert "docker volume prune" not in script
