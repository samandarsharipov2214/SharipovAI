"""Explicit reversible encoding migration; never runs at import or startup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.project_db_retention import _valid_backup_evidence
from storage import ProjectDatabase
from storage.evidence_codec import MARKER, NAMESPACE, pack, unpack


def convert(db: ProjectDatabase, *, after: str = '', batch_size: int = 100, expand: bool = False) -> dict:
    if not 1 <= batch_size <= 500:
        raise ValueError('batch size outside bounds')
    with db.connect() as connection:
        candidates = db._fetchall(connection,
            'SELECT item_key,length(value_json) AS chars FROM project_kv WHERE namespace=? AND item_key>? ORDER BY item_key LIMIT ?',
            (NAMESPACE, after, batch_size))
        rows = []
        used = 0
        for item in candidates:
            if item['chars'] > 16 * 1024**2:
                raise ValueError('evidence row exceeds migration memory budget')
            if rows and used + item['chars'] > 4 * 1024**2:
                break
            row = db._fetchone(connection, 'SELECT item_key,value_json FROM project_kv WHERE namespace=? AND item_key=?', (NAMESPACE, item['item_key']))
            used += len(row['value_json'].encode())
            rows.append(row)
    changed = saved = 0
    replacements = []
    processed = []
    expanded_bytes = 0
    for row in rows:
        raw = row['value_json']
        original = unpack(raw)
        if processed and expanded_bytes + len(original.encode()) > 4 * 1024**2:
            break
        processed.append(row)
        expanded_bytes += len(original.encode())
        target = original if expand else (raw if original != raw else pack(NAMESPACE, raw))
        if unpack(target) != original:
            raise ValueError('lossless encoding verification failed')
        if target != raw:
            replacements.append((target, NAMESPACE, row['item_key'], raw))
            saved += len(raw.encode()) - len(target.encode())
    with db.connect() as connection:
        try:
            db._begin(connection, immediate=True)
            for params in replacements:
                cursor = db._execute(connection,
                    'UPDATE project_kv SET value_json=? WHERE namespace=? AND item_key=? AND value_json=?', params)
                if cursor.rowcount != 1:
                    raise RuntimeError('evidence changed during conversion')
                changed += 1
            connection.commit()
        except BaseException:
            connection.rollback(); raise
    return {'after': processed[-1]['item_key'] if processed else after, 'scanned': len(processed),
            'changed': changed, 'payload_bytes_saved': saved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-evidence', type=Path, required=True)
    parser.add_argument('--batches', type=int, default=100)
    parser.add_argument('--expand', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.batches <= 10000 or not _valid_backup_evidence(args.backup_evidence):
        parser.error('bounded batches and hash-verified restored backup required')
    db = ProjectDatabase()
    key = 'expand_cursor' if args.expand else 'compression_cursor'
    state = db.get_json('storage_lifecycle', key)
    after = state['value']['after'] if state else ''
    total = {'scanned': 0, 'changed': 0, 'payload_bytes_saved': 0}
    for _ in range(args.batches):
        result = convert(db, after=after, expand=args.expand)
        after = result['after']
        for name in total:
            total[name] += result[name]
        db.put_json('storage_lifecycle', key, result)
        if db.backend == 'sqlite':
            with db.connect() as connection:
                checkpoint = connection.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            if checkpoint[1] - checkpoint[2] > 32768:
                total['wal_backlog_stop'] = True
                break
        if not result['scanned']:
            total['complete'] = True
            break
    print(json.dumps(total))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
