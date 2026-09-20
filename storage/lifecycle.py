"""Explicit maintenance for proven operational events; unknown owners fail closed.

Canonical evidence, PAPER, Learning, messages and audit rows are never eligible.
The existing (namespace, entity_type, entity_id, created_at_ms) index supports
both entity keyset traversal and each bounded retention selection.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import tempfile
from pathlib import Path

from storage import ProjectDatabase

POLICIES = {"market": "quote", "news_fetch_observations": "source_fetch"}
DEFAULT_RETAIN_DAYS = 7
MAX_ROWS = 5000


def verify_archive(path: Path) -> tuple[dict, list[dict]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        header = json.loads(stream.readline(65536))
        if header.get("schema") != 1 or header.get("classification") != "disposable_operational":
            raise ValueError("unknown archive ownership")
        rows = []
        digest = hashlib.sha256()
        total_bytes = 0
        while line := stream.readline(1024**2 + 1):
            total_bytes += len(line.encode())
            if total_bytes > 32 * 1024**2:
                raise ValueError("archive exceeds aggregate byte budget")
            if len(rows) >= MAX_ROWS or len(line) > 1024**2:
                raise ValueError("archive exceeds bounds")
            digest.update(line.encode())
            row = json.loads(line)
            if POLICIES.get(row.get("namespace")) != row.get("entity_type"):
                raise ValueError("archive contains canonical or ambiguous data")
            rows.append(row)
        if len(rows) != header["count"] or digest.hexdigest() != header["sha256"]:
            raise ValueError("archive integrity failure")
    return header, rows


def archive_rows(root: Path, rows: list[dict], cutoff: int) -> Path:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = ''.join(json.dumps(row, sort_keys=True, ensure_ascii=True) + '\n' for row in rows).encode()
    digest = hashlib.sha256(data).hexdigest()
    header = {"schema": 1, "classification": "disposable_operational", "table": "project_events",
              "columns": list(rows[0]), "count": len(rows), "sha256": digest,
              "cutoff_ms": cutoff, "min_ms": min(r['created_at_ms'] for r in rows),
              "max_ms": max(r['created_at_ms'] for r in rows), "archived_at_ms": int(time.time()*1000)}
    target = root / f'operational-v1-{digest}.jsonl.gz'
    if not target.exists():
        fd, temporary_name = tempfile.mkstemp(prefix='.operational-', suffix='.partial', dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, 'wb') as raw:
                with gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
                    stream.write((json.dumps(header, sort_keys=True)+'\n').encode())
                    stream.write(data)
                raw.flush(); os.fsync(raw.fileno())
            verify_archive(temporary)
            # Hard link publishes without ever replacing an existing archive.
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
    _, restored = verify_archive(target)
    if restored != rows:
        raise ValueError('archive readback differs from selected rows')
    return target


def retain(db: ProjectDatabase, archive_dir: Path, *, retain_days: int = 7,
           batch_size: int = 100, apply: bool = False, max_rows: int = MAX_ROWS) -> dict:
    if not 7 <= retain_days <= 30 or not 1 <= batch_size <= 500 or not 1 <= max_rows <= MAX_ROWS:
        raise ValueError('retention configuration outside safe bounds')
    cutoff = (int(time.time()) // 86400 - retain_days) * 86400000
    state = db.get_json('storage_lifecycle', 'operational_cursor')
    cursors = dict(state['value']) if state else {}
    selected = []
    selected_bytes = 0
    byte_limit = False
    deadline = time.monotonic() + 20
    for namespace, entity_type in POLICIES.items():
        cursor = str(cursors.get(namespace, ''))
        with db.connect() as connection:
            if db.backend == "sqlite":
                connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
            entities = db._fetchall(connection,
                'SELECT DISTINCT entity_id FROM project_events WHERE namespace=? AND entity_type=? AND entity_id>? ORDER BY entity_id LIMIT 100',
                (namespace, entity_type, cursor))
            for entity in entities:
                entity_id = entity['entity_id']
                query = db._execute(connection,
                    'SELECT event_id,namespace,entity_type,entity_id,payload_json,created_at_ms FROM project_events WHERE namespace=? AND entity_type=? AND entity_id=? AND created_at_ms<? ORDER BY created_at_ms LIMIT ?',
                    (namespace, entity_type, entity_id, cutoff, max_rows-len(selected)))
                columns = [item.name if hasattr(item, 'name') else item[0] for item in query.description]
                while raw := query.fetchone():
                    row = dict(zip(columns, raw))
                    size = len(row['payload_json'].encode())
                    if size > 65536:
                        raise ValueError('unexpected operational payload; ownership requires review')
                    if selected_bytes + size > 4 * 1024**2:
                        byte_limit = True
                        break
                    selected.append(row)
                    selected_bytes += size
                query.close()
                # Revisit a partially drained entity on the next invocation.
                if byte_limit or len(selected) >= max_rows or time.monotonic() >= deadline:
                    break
                cursor = entity_id
            else:
                if len(entities) < 100:
                    cursor = ''
        cursors[namespace] = cursor
        if byte_limit or len(selected) >= max_rows or time.monotonic() >= deadline:
            break
    result = {'cutoff_ms': cutoff, 'selected': len(selected), 'deleted': 0,
              'archive': None, 'batch_size': batch_size, 'retain_days': retain_days,
              'backlog_lower_bound': len(selected), 'checked_at_ms': int(time.time()*1000)}
    if apply:
        if selected:
            path = archive_rows(archive_dir, selected, cutoff)
            result['archive'] = path.name
            for start in range(0, len(selected), batch_size):
                with db.connect() as connection:
                    try:
                        db._begin(connection, immediate=True)
                        for row in selected[start:start+batch_size]:
                            # A changed row remains hot; the archive cannot justify its deletion.
                            deleted = db._execute(connection,
                                'DELETE FROM project_events WHERE event_id=? AND namespace=? AND entity_type=? AND created_at_ms=? AND payload_json=?',
                                (row['event_id'], row['namespace'], row['entity_type'], row['created_at_ms'], row['payload_json']))
                            result['deleted'] += deleted.rowcount
                        connection.commit()
                    except BaseException:
                        connection.rollback(); raise
                if db.backend == 'sqlite':
                    with db.connect() as connection:
                        checkpoint = connection.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
                    if checkpoint[1] - checkpoint[2] > 32768:
                        # Reader-pinned WAL backlog: stop instead of adding unbounded frames.
                        result['wal_backlog_stop'] = True
                        break
        db.put_json('storage_lifecycle', 'operational_cursor', cursors)
        expired = 0
        # Only verified disposable operational archives expire, after 30 days.
        # Canonical evidence and unknown archive formats are never candidates.
        for path in list(archive_dir.glob('operational-v1-*.jsonl.gz'))[:10000]:
            if path.stat().st_mtime < time.time()-30*86400:
                header, _ = verify_archive(path)
                if header['archived_at_ms'] < int(time.time()*1000)-30*86400000:
                    path.unlink()
                    expired += 1
        result['expired_archives'] = expired
        db.put_json('storage_lifecycle', 'last_retention', result)
    return result
