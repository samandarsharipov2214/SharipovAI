from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT_BACKUP = ROOT / "deploy" / "vps" / "export_backup.sh"
UPDATE_SCRIPT = ROOT / "deploy" / "vps" / "update_from_main.sh"


def test_offline_backup_uses_read_only_named_volume_and_no_network() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert "source_mode='stopped-volume-readonly'" in source
    assert '--network none' in source
    assert '--read-only' in source
    assert '--security-opt no-new-privileges:true' in source
    assert '--cap-drop ALL' in source
    assert '--cap-add DAC_READ_SEARCH' in source
    assert '-v "$volume_name:/source:ro"' in source
    assert '-v "$work/data:/backup"' in source
    assert "docker volume inspect \"$volume_name\"" in source
    assert "docker image inspect \"$image_name\"" in source


def test_offline_backup_consolidates_sqlite_and_forbids_symlinks() -> None:
    source = EXPORT_BACKUP.read_text(encoding="utf-8")

    assert "data symlink is forbidden in offline backup" in source
    assert "unsupported data entry in offline backup" in source
    assert 'with sqlite3.connect(db) as src, sqlite3.connect(clean) as dst:' in source
    assert 'src.backup(dst)' in source
    assert 'PRAGMA quick_check' in source
    assert 'os.replace(clean, db)' in source
    assert 'source_mode' in source


def test_updater_uses_target_backup_exporter_before_checkout() -> None:
    source = UPDATE_SCRIPT.read_text(encoding="utf-8")

    assert 'git -C "${APP_DIR}" show "${target_sha}:deploy/vps/export_backup.sh"' in source
    assert 'APP_DIR="${APP_DIR}" COMPOSE_DIR="${compose_dir}" bash "${backup_exporter_tmp}"' in source
    assert source.index('bash "${backup_exporter_tmp}"') < source.index('git -C "${APP_DIR}" reset --hard "${target_sha}"')
