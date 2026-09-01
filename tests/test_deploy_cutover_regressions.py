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


def test_storage_guard_cleanup_emits_docker_evidence_and_runs_bounded_prune(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    record = tmp_path / "docker-calls.txt"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$RECORD_FILE"
[ "$#" -eq 2 ]
[ "$1" = "system" ]
[ "$2" = "df" ]
printf 'TYPE TOTAL ACTIVE SIZE RECLAIMABLE\\n'
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
    assert "STORAGE_GUARD_EVIDENCE_UTC" in result.stdout
    assert "STORAGE_GUARD_CLEANUP_OK" in result.stdout
    assert "STORAGE_GUARD_CLEANUP_SKIPPED" not in result.stdout
    calls = record.read_text(encoding="utf-8")
    assert "system df" in calls
    assert "system prune" not in calls
    assert "volume prune" not in calls


def test_storage_guard_never_uses_unbounded_prune_or_volume_delete() -> None:
    script = (ROOT / "scripts" / "deploy_storage_guard.sh").read_text(encoding="utf-8")
    assert "prune_disposable_disk.sh" in script
    for forbidden in (
        "docker system prune",
        "docker image prune",
        "docker volume prune",
        "docker container prune",
        "docker buildx prune",
        "docker rmi",
        "docker rm",
        "docker builder prune",
    ):
        assert forbidden not in script
