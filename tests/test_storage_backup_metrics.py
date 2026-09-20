import json
import time
from pathlib import Path

import pytest

from storage import ProjectDatabase
from storage.metrics import collect


def inaccessible_backup(monkeypatch, backup):
    original = Path.stat
    def stat(path, *args, **kwargs):
        if path.is_relative_to(backup):
            raise PermissionError('private host backup directory')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', stat)


def test_inaccessible_host_backup_does_not_discard_storage_sample(tmp_path, monkeypatch):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "project.db"}')
    db.initialize()
    inaccessible_backup(monkeypatch, tmp_path / 'private-backup')
    result = collect(db, tmp_path / 'private-backup')
    assert result['db_bytes'] > 0
    assert result['backup_bytes'] is None
    assert result['backup_error'] == 'PermissionError'
    assert 'backup_stale' in result['alerts']
    assert json.loads((tmp_path / 'storage-metrics.json').read_text()) == result


def test_published_archive_metadata_works_without_host_directory_access(tmp_path, monkeypatch):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "project.db"}')
    db.initialize()
    inaccessible_backup(monkeypatch, tmp_path / 'private-backup')
    completed = int(time.time()*1000)-15000
    result = collect(db, tmp_path / 'private-backup', verified_backup_bytes=123456,
                     verified_backup_at_ms=completed)
    assert result['backup_bytes'] == 123456
    assert 15 <= result['backup_age_seconds'] < 20
    assert result['backup_source'] == 'verified_exporter'
    assert 'backup_stale' not in result['alerts']
    assert 'backup_error' not in result


@pytest.mark.parametrize('size,at', [(0,1), (1,None), (None,1), (1,0), (1,10**20)])
def test_invalid_archive_observation_is_rejected(tmp_path, size, at):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "project.db"}')
    with pytest.raises(ValueError, match='supplied together and valid'):
        collect(db, tmp_path, verified_backup_bytes=size, verified_backup_at_ms=at)
