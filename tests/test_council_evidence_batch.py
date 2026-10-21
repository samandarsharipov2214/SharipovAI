"""Isolated SQLite evidence persistence; no execution or production data."""
from contextlib import contextmanager
from types import SimpleNamespace
import time
import pytest
from autonomous_trading.council_provider import AutonomousCouncilProposalProvider
from storage import ProjectDatabase
from test_canonical_autonomous_runtime_v2 import _positive_news, _state


class EvidenceStream:
    def evidence(self, symbol):
        return {'symbol':symbol, 'verified':True, 'synthetic_fallback_used':False,
                'consensus_sources':('bybit','binance','okx'),
                'ws_consensus_deviation_percent':0.01,
                'consensus_maximum_deviation_percent':0.01}


@pytest.mark.parametrize('commit_delay,eligible', [(0.45, True), (1.2, False), (3.0, False)])
def test_council_commit_latency_does_not_multiply_across_evidence(tmp_path, monkeypatch, commit_delay, eligible):
    db=ProjectDatabase(f'sqlite:///{tmp_path / "paper.db"}');db.initialize()
    provider=AutonomousCouncilProposalProvider(db,EvidenceStream(),news_reader=_positive_news)
    clock={'now':time.time()};monkeypatch.setattr(time,'time',lambda:clock['now'])
    ts=int(clock['now']*1000)-100
    quote=SimpleNamespace(symbol='BTCUSDT',price=60000.,change_24h_percent=2.4,
                          volume_24h=250000000.,received_at_unix_ms=ts)
    connect=db.connect;commits=[]
    class Connection:
        def __init__(self,raw):self.raw=raw
        def __getattr__(self,key):return getattr(self.raw,key)
        def commit(self):
            self.raw.commit();commits.append(clock['now']);clock['now']+=commit_delay
    @contextmanager
    def delayed_connect():
        with connect() as c:yield Connection(c)
    monkeypatch.setattr(db,'connect',delayed_connect)
    proposal=provider('BTCUSDT',quote,_state())
    assert (proposal is not None)==eligible
    decision=f'paper-BTCUSDT-{ts}'
    for ns,prefix in [('council_market_evidence','market'),('council_news_assessments','news'),
                      ('portfolio_snapshots','portfolio'),('cost_snapshots','cost'),('risk_assessments','risk')]:
        row=db.get_json(ns,f'{prefix}-{decision}')
        assert row and row['version']==1 and row['value']['decision_id']==decision
    if eligible:
        assert len(commits)==2  # one immutable bundle, one scheduler checkpoint
        assert proposal.evidence_packet.market_timestamp_ms==ts
    elif commit_delay >= 2:
        assert db.get_json('autonomous_council_runtime','BTCUSDT') is None
    else:
        # A late scheduler checkpoint is diagnostic state, never permission to trade.
        assert db.get_json('autonomous_council_runtime','BTCUSDT') is not None


def database(tmp_path):
    db=ProjectDatabase(f'sqlite:///{tmp_path / "bundle.db"}');db.initialize();return db


def test_immutable_bundle_replay_preserves_encoded_content_version_and_time(tmp_path):
    db=database(tmp_path)
    entries=[('council_news_assessments','news-1',{'text':'repeated ' * 1000}),
             ('cost_snapshots','cost-1',{'fees':0.1})]
    db.put_immutable_json_batch(entries)
    before=[db.get_json(ns,key) for ns,key,_ in entries]
    db.put_immutable_json_batch(entries)
    assert [db.get_json(ns,key) for ns,key,_ in entries]==before
    assert [x['value'] for x in before]==[e[2] for e in entries]


def test_immutable_bundle_collision_rolls_back_earlier_new_entries(tmp_path):
    from storage import VersionConflict
    db=database(tmp_path);db.put_json('z','existing',{'value':1})
    before=db.get_json('z','existing')
    with pytest.raises(VersionConflict,match='immutable evidence collision'):
        db.put_immutable_json_batch([('a','new',{'value':2}),('z','existing',{'value':3})])
    assert db.get_json('a','new') is None
    assert db.get_json('z','existing')==before


def test_immutable_bundle_does_not_publish_partial_rows_on_write_failure(tmp_path,monkeypatch):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    db=database(tmp_path);first=Event();release=Event();execute=db._execute
    def fail_second(connection,query,params=()):
        if 'INSERT INTO project_kv' in query:
            if params[:2]==('b','two'):
                first.set();assert release.wait(5)
                raise sqlite3.OperationalError('injected write failure')
        return execute(connection,query,params)
    monkeypatch.setattr(db,'_execute',fail_second)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(db.put_immutable_json_batch,[('a','one',{}),('b','two',{})])
        try:
            assert first.wait(5)
            assert db.get_json('a','one') is None  # independent real SQLite reader
        finally:release.set()
        with pytest.raises(sqlite3.OperationalError,match='injected'):task.result(timeout=5)
    assert db.get_json('a','one') is None and db.get_json('b','two') is None


def test_concurrent_identical_bundles_are_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    db=database(tmp_path);entries=[('risk_assessments','risk-1',{'blocked':True}),('cost_snapshots','cost-1',{'fee':1})]
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:db.put_immutable_json_batch(entries),range(8)))
    assert all(db.get_json(ns,key)['version']==1 for ns,key,_ in entries)


@pytest.mark.parametrize('entries',[[],[('a','one',{}),('a','one',{})],[('a',str(i),{}) for i in range(65)]])
def test_immutable_bundle_rejects_unbounded_or_duplicate_input(tmp_path,entries):
    db=database(tmp_path)
    with pytest.raises(ValueError):db.put_immutable_json_batch(entries)
    with db.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM project_kv').fetchone()[0]==0
