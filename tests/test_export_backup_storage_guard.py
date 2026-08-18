from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "vps" / "export_backup.sh"


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_export_backup_script_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_backup_fails_closed_before_staging_when_disk_headroom_is_low() -> None:
    text = _script()
    assert "SHARIPOVAI_BACKUP_MIN_FREE_DISK_GB:-20" in text
    assert "SHARIPOVAI_BACKUP_RESERVE_MIB:-512" in text
    assert "df -P -B1" in text
    assert "require_free_space 0 'initial preflight'" in text
    assert "require_free_space \"$((source_bytes * 2))\" 'before staging persistent data'" in text
    assert "require_free_space \"$staged_bytes\" 'before archive creation'" in text
    assert text.index("require_free_space 0 'initial preflight'") < text.index("work=$(mktemp -d")


def test_backup_only_removes_stale_staging_after_exclusive_lock() -> None:
    text = _script()
    lock = text.index("flock -n 9")
    cleanup_call = text.index("cleanup_stale_staging\n")
    assert lock < cleanup_call
    assert "-type d -name '.staging-*' -print0" in text
    assert '[[ "$stale" == "$BACKUP_DIR"/.staging-* ]]' in text
    assert 'rm -rf -- "$stale"' in text
    assert "docker system prune" not in text
    assert "docker image prune" not in text
    assert "docker volume prune" not in text


def test_backup_helper_is_bounded_identifiable_and_still_isolated() -> None:
    text = _script()
    assert "SHARIPOVAI_BACKUP_HELPER_TIMEOUT_SECONDS:-300" in text
    assert 'timeout --foreground --kill-after=10s "${HELPER_TIMEOUT_SECONDS}s"' in text
    assert '--name "$helper_name"' in text
    assert "--label 'com.sharipovai.role=backup-helper'" in text
    assert '--label "com.sharipovai.run=$run_id"' in text
    assert "--no-healthcheck" in text
    assert "--network none" in text
    assert "--read-only" in text
    assert "--security-opt no-new-privileges:true" in text
    assert "--cap-drop ALL" in text
    assert '-v "$volume_name:/source:ro"' in text


def test_helper_cleanup_requires_exact_role_and_run_labels() -> None:
    text = _script()
    assert 'helper_id=$(docker inspect --format \'{{.Id}}\' "$helper_name"' in text
    assert 'role=$(docker inspect --format \'{{index .Config.Labels "com.sharipovai.role"}}\'' in text
    assert 'helper_run=$(docker inspect --format \'{{index .Config.Labels "com.sharipovai.run"}}\'' in text
    assert "[[ \"$role\" == 'backup-helper' && \"$helper_run\" == \"$run_id\" ]]" in text
    assert 'docker rm -f "$helper_id"' in text
    assert "refusing to remove helper candidate with unexpected labels" in text


def test_hashing_is_streaming_and_host_heavy_work_is_deprioritized() -> None:
    text = _script()
    assert ".read_bytes()" not in text
    assert 'handle.read(1024 * 1024)' in text
    assert "ionice -c2 -n7 nice -n 10" in text
    assert 'run_low_priority tar -C "$work"' in text
    assert 'run_low_priority sha256sum "$archive_tmp"' in text


def test_archive_is_published_only_after_complete_partial_file() -> None:
    text = _script()
    assert 'archive_tmp=$(mktemp "$BACKUP_DIR/.sharipovai-$stamp.tar.gz.partial-XXXXXX")' in text
    assert 'run_low_priority tar -C "$work" -czf "$archive_tmp"' in text
    assert 'mv "$archive_checksum_tmp" "$archive.sha256"' in text
    assert 'mv "$archive_tmp" "$archive"' in text
    assert '[[ "$candidate" == "$BACKUP_DIR"/.sharipovai-*.partial-* ]]' in text
    assert 'rm -f -- "$candidate"' in text
