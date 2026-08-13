from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT_BACKUP = ROOT / "deploy" / "vps" / "export_backup.sh"
UPDATE_SCRIPT = ROOT / "deploy" / "vps" / "update_from_main.sh"


def test_backup_helper_uses_read_only_named_volume_and_no_network() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert "source_mode='stopped-volume-readonly'" in source
    assert '--network none' in source
    assert '--read-only' in source
    assert '--security-opt no-new-privileges:true' in source
    assert '--cap-drop ALL' in source
    assert '--cap-add DAC_READ_SEARCH' in source
    assert '-v "$volume_name:/source:ro"' in source
    assert '-v "$work/data:/backup"' in source
    assert '"$image_name" - "$source_mode" <<\'PY\'' in source
    assert "docker volume inspect \"$volume_name\"" in source
    assert "docker image inspect \"$image_name\"" in source


def test_backup_uses_sqlite_snapshot_and_forbids_symlinks() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert "data symlink is forbidden in backup" in source
    assert "unsupported data entry in backup" in source
    assert 'sqlite_suffixes = (".db", ".sqlite", ".sqlite3")' in source
    assert 'sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)' in source
    assert 'src.backup(dst)' in source
    assert 'PRAGMA quick_check' in source
    assert 'for db in sorted(source.iterdir()):' in source
    assert 'db.suffix.lower() not in sqlite_suffixes' in source
    assert 'item.suffix.lower() in sqlite_suffixes or item.name.endswith(("-wal", "-shm"))' in source
    assert 'source_mode' in source


def test_running_backup_does_not_depend_on_application_container_root() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert "source_mode='running-volume-readonly'" in source
    assert "isolated read-only helper" in source
    assert 'docker exec --user 0:0' not in source
    assert ".backup-export" not in source


def test_backup_keeps_production_data_permissions_and_fails_closed() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert "chmod 777" not in source
    assert "chmod 755 /var/lib/sharipovai" not in source
    assert '-v "$volume_name:/source:ro"' in source
    assert "--cap-add DAC_READ_SEARCH" in source
    assert "--cap-add SYS_ADMIN" not in source
    assert "|| fail 'persistent data volume could not be resolved safely'" in source
    assert "backup contains no files" in source


def test_updater_uses_target_backup_exporter_before_checkout() -> None:
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert 'git -C "${APP_DIR}" show "${target_sha}:deploy/vps/export_backup.sh"' in source
    assert 'APP_DIR="${APP_DIR}" COMPOSE_DIR="${compose_dir}" bash "${backup_exporter_tmp}"' in source
    assert source.index('bash "${backup_exporter_tmp}"') < source.index('git -C "${APP_DIR}" reset --hard "${target_sha}"')
