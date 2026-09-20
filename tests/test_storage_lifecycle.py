from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

from scripts.compress_council_evidence import convert
from storage import ProjectDatabase, list_json_items
from storage.evidence_codec import MARKER, pack, unpack
from storage.lifecycle import archive_rows, retain, verify_archive
from tests.test_backup_phase_budget import embedded
from tools.sqlite_logical_restore import restore_database


def test_logical_snapshot_restores_wal_blobs_unicode_fts_and_transaction(tmp_path):
    source = tmp_path / 'live.db'
    writer = sqlite3.connect(source)
    writer.execute('PRAGMA journal_mode=WAL')
    writer.executescript('CREATE TABLE evidence(id INTEGER PRIMARY KEY, value, data BLOB); CREATE INDEX evidence_idx ON evidence(value); CREATE VIRTUAL TABLE words USING fts5(content);')
    writer.execute('INSERT INTO evidence VALUES (1,?,?)', ('hello\n世界\x00tail', b'\x00\xff'))
    writer.execute("INSERT INTO words VALUES ('preserved learning')")
    writer.commit()
    reader = sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)
    reader.execute('BEGIN')
    reader.execute('SELECT * FROM evidence').fetchall()
    writer.execute("INSERT INTO evidence VALUES (2,'after snapshot',NULL)")
    writer.commit()
    helper = embedded('LOGICAL_SNAPSHOT')
    archive = tmp_path / 'snapshot.gz'
    metadata = helper['logical_snapshot'](reader, archive, helper['StagingBudget'](tmp_path, 0))
    reader.close()
    target = tmp_path / 'restore.db'
    restore_database(archive, target, metadata, reserve_bytes=0)
    restored = sqlite3.connect(target)
    assert restored.execute('SELECT * FROM evidence').fetchall() == [(1, 'hello\n世界\x00tail', b'\x00\xff')]
    assert restored.execute("SELECT content FROM words WHERE words MATCH 'learning'").fetchall() == [('preserved learning',)]
    assert writer.execute('SELECT count(*) FROM evidence').fetchone()[0] == 2
    restored.close(); writer.close()
    bad = dict(metadata, stream_sha256='0'*64)
    with pytest.raises(Exception, match='integrity'):
        restore_database(archive, tmp_path/'bad.db', bad, reserve_bytes=0)
    assert not (tmp_path/'bad.db').exists()


def test_lossless_encoding_and_rollback_preserve_versions_and_timestamps(tmp_path):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "test.db"}'); db.initialize()
    payload = {'decision_id': 'decision-1', 'lineage': ['complete evidence 世界']*500}
    raw = json.dumps(payload, indent=2, ensure_ascii=False)
    with db.connect() as c:
        c.execute('INSERT INTO project_kv VALUES (?,?,?,?,?)', ('council_news_assessments', 'news-1', raw, 7, 1234))
    assert convert(db)['changed'] == 1
    document = db.get_json('council_news_assessments', 'news-1')
    assert document == {'value': payload, 'version': 7, 'updated_at_ms': 1234}
    assert list_json_items(db, 'council_news_assessments')[0]['value'] == payload
    assert convert(db)['changed'] == 0
    assert convert(db, expand=True)['changed'] == 1
    with db.connect() as c:
        assert c.execute('SELECT value_json FROM project_kv').fetchone()[0] == raw
    encoded = json.loads(pack('council_news_assessments', raw))
    encoded[MARKER]['sha256'] = '0'*64
    with pytest.raises(ValueError, match='integrity'):
        unpack(json.dumps(encoded))
    assert pack('paper_trades', raw) == raw


def test_retention_is_allowlisted_archived_bounded_and_idempotent(tmp_path):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "test.db"}'); db.initialize()
    old = int(time.time()*1000)-40*86400000
    for i in range(11):
        db.append_event('market', 'quote', 'BTC', {'price': i}, created_at_ms=old)
    for ns in ['learning', 'audit', 'paper_trades', 'market_cache', 'unknown_owner', 'decision_quality']:
        db.append_event(ns, 'quote', 'canonical', {'keep': True}, created_at_ms=old)
    db.append_event('market', 'quote', 'BTC', {'recent': True})
    dry = retain(db, tmp_path/'archive', max_rows=5)
    assert dry['selected'] == 5 and dry['deleted'] == 0
    assert not (tmp_path/'archive').exists()
    removed = 0
    for _ in range(4):
        result = retain(db, tmp_path/'archive', apply=True, max_rows=5, batch_size=2)
        removed += result['deleted']
    assert removed == 11
    assert len(db.list_events('market')) == 1
    for ns in ['learning', 'audit', 'paper_trades', 'market_cache', 'unknown_owner', 'decision_quality']:
        assert len(db.list_events(ns)) == 1
    archives = list((tmp_path/'archive').glob('*.gz'))
    assert sum(verify_archive(p)[0]['count'] for p in archives) == 11


def test_retention_query_uses_existing_covering_prefix(tmp_path):
    db = ProjectDatabase(f'sqlite:///{tmp_path / "test.db"}'); db.initialize()
    with db.connect() as c:
        plan = str([tuple(r) for r in c.execute('EXPLAIN QUERY PLAN SELECT event_id FROM project_events WHERE namespace=? AND entity_type=? AND entity_id=? AND created_at_ms<? ORDER BY created_at_ms LIMIT 100', ('market','quote','BTC',1))])
    assert 'project_events_lookup_idx' in plan and 'TEMP B-TREE' not in plan


def test_schema2_materialization_checks_manifest_and_restores(tmp_path):
    from tools.backup_integrity import verify_snapshot, sha256
    from tools.sqlite_logical_restore import materialize
    from datetime import datetime, timezone
    root = tmp_path/'snapshot'; (root/'data').mkdir(parents=True)
    source = sqlite3.connect(':memory:')
    source.execute('CREATE TABLE paper(id TEXT PRIMARY KEY, value TEXT)')
    source.execute("INSERT INTO paper VALUES ('trade-1','preserved')"); source.commit()
    helper = embedded('LOGICAL_SNAPSHOT')
    path = root/'data/paper.db.sql.jsonl.gz'
    info = helper['logical_snapshot'](source, path, helper['StagingBudget'](tmp_path, 0))
    info.update(path=path.name, database_path='paper.db')
    manifest = {'schema': 2, 'created_at': datetime.now(timezone.utc).isoformat(), 'file_count': 1,
                'files': [{'path': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path)}],
                'sqlite_logical': [info]}
    (root/'manifest.json').write_text(json.dumps(manifest))
    verified = verify_snapshot(root)
    materialize(root, verified)
    assert verify_snapshot(root)['schema'] == 1
    with sqlite3.connect(root/'data/paper.db') as restored:
        assert restored.execute('SELECT * FROM paper').fetchall() == [('trade-1','preserved')]


def test_archive_failure_never_deletes_hot_rows(tmp_path, monkeypatch):
    import storage.lifecycle as lifecycle
    db = ProjectDatabase(f'sqlite:///{tmp_path/"db"}'); db.initialize()
    db.append_event('news_fetch_observations', 'source_fetch', 'article', {}, created_at_ms=1)
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(lifecycle, 'archive_rows', fail)
    with pytest.raises(OSError):
        lifecycle.retain(db, tmp_path/'archive', apply=True)
    assert len(db.list_events('news_fetch_observations')) == 1
