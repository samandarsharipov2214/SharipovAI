"""Bounded storage sampling for the existing General Controller health center."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from storage import ProjectDatabase

TRACKED = {'project_kv': ('council_news_assessments', 'paper_v2_decisions', 'trading_candidates'),
           'project_events': ('market', 'news_fetch_observations', 'decision_quality')}


def collect(db: ProjectDatabase, backup_dir: Path, *, verified_backup_bytes: int | None = None,
            verified_backup_at_ms: int | None = None) -> dict:
    now = int(time.time()*1000)
    if verified_backup_bytes is not None or verified_backup_at_ms is not None:
        if (type(verified_backup_bytes) is not int or verified_backup_bytes <= 0
                or type(verified_backup_at_ms) is not int
                or not 0 < verified_backup_at_ms <= now + 300000):
            raise ValueError('verified backup size and timestamp must be supplied together and valid')
    if db.backend != 'sqlite':
        return {'status': 'not_sqlite', 'checked_at_ms': int(time.time()*1000)}
    path = Path(db.dsn.removeprefix('sqlite:///'))
    result = {'checked_at_ms': now, 'db_bytes': path.stat().st_size,
              'wal_bytes': Path(str(path)+'-wal').stat().st_size if Path(str(path)+'-wal').exists() else 0,
              'filesystem_free_bytes': shutil.disk_usage(path.parent).free, 'namespaces': [], 'alerts': []}
    metrics_path = path.parent / 'storage-metrics.json'
    try:
        previous = json.loads(metrics_path.read_text())
        elapsed = (now-previous['checked_at_ms'])/1000
        result['growth_bytes_per_second'] = max(0, (result['db_bytes']-previous['db_bytes'])/elapsed) if elapsed > 0 else None
    except (OSError, ValueError, KeyError):
        result['growth_bytes_per_second'] = None
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=1) as connection:
        for table, namespaces in TRACKED.items():
            for namespace in namespaces:
                deadline = time.monotonic()+1
                connection.set_progress_handler(lambda: int(time.monotonic()>deadline), 10000)
                try:
                    count = connection.execute(f'SELECT count(*) FROM {table} WHERE namespace=?', (namespace,)).fetchone()[0]
                    result['namespaces'].append({'table': table, 'namespace': namespace, 'rows': count, 'exact': True})
                except sqlite3.OperationalError:
                    result['namespaces'].append({'table': table, 'namespace': namespace, 'rows': None, 'exact': False})
        connection.set_progress_handler(None, 0)
    retention = db.get_json('storage_lifecycle', 'last_retention')
    result['retention'] = retention['value'] if retention else None
    result.update(backup_age_seconds=None, backup_bytes=None)
    if verified_backup_bytes is not None:
        # The host exporter supplies these only after verified publication. Its
        # private backup directory is intentionally inaccessible to the app UID.
        result.update(backup_age_seconds=max(0, (now-verified_backup_at_ms)/1000),
                      backup_bytes=verified_backup_bytes, backup_source='verified_exporter')
    else:
        latest = backup_dir / 'latest.tar.gz'
        try:
            if latest.exists() and latest.with_name('latest.tar.gz.sha256').exists():
                info = latest.stat()
                result.update(backup_age_seconds=max(0, now/1000-info.st_mtime), backup_bytes=info.st_size)
        except OSError as exc:
            result['backup_error'] = type(exc).__name__
    if result['wal_bytes'] > 512*1024**2: result['alerts'].append('wal_growth')
    if result['filesystem_free_bytes'] < 22*1024**3: result['alerts'].append('disk_low')
    if result['backup_age_seconds'] is None or result['backup_age_seconds'] > 7200: result['alerts'].append('backup_stale')
    if (result['growth_bytes_per_second'] or 0)*86400 > 256*1024**2: result['alerts'].append('abnormal_database_growth')
    if (result['retention'] is None or result['retention']['selected'] >= 5000
            or now-result['retention']['checked_at_ms'] > 7200000): result['alerts'].append('retention_backlog')
    result['status'] = 'degraded' if result['alerts'] else 'ok'
    temporary = metrics_path.with_suffix('.partial')
    with temporary.open('w') as handle:
        json.dump(result, handle, sort_keys=True)
        handle.flush(); os.fsync(handle.fileno())
    temporary.replace(metrics_path)
    return result


def read_metrics() -> dict:
    try:
        db = ProjectDatabase()
    except Exception:
        return {"alerts": ["storage_metrics_unavailable"]}
    root = Path(db.dsn.removeprefix('sqlite:///')).parent if db.backend == 'sqlite' else Path(os.getenv('SHARIPOVAI_DATA_DIR', 'data'))
    try:
        value = json.loads((root / 'storage-metrics.json').read_text())
        if time.time()*1000-value['checked_at_ms'] > 7200000:
            value['alerts'] = list(set(value.get('alerts', [])) | {'storage_metrics_stale'})
        return value
    except (OSError, ValueError, KeyError):
        return {'alerts': ['storage_metrics_unavailable']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verified-backup-bytes', type=int)
    parser.add_argument('--verified-backup-at-ms', type=int)
    args = parser.parse_args()
    print(json.dumps(collect(ProjectDatabase(), Path(os.getenv('SHARIPOVAI_BACKUP_DIR', '/workspace/deploy/vps/backups')),
                             verified_backup_bytes=args.verified_backup_bytes,
                             verified_backup_at_ms=args.verified_backup_at_ms), sort_keys=True))
