import hashlib
import json
import sqlite3

import pytest

from scripts.astra_paper_audit import collect, financials


def pair():
    return [dict(trade_id='b', decision_id='d',symbol='BTCUSDT', side='BUY', price=100., quantity=1.,fee=.1,created_at_ms=1),
            dict(trade_id='s', decision_id='d',symbol='BTCUSDT', side='SELL', price=100.05, quantity=1.,fee=.10005,net_pnl=-.15005,created_at_ms=2)]


def test_fees_explain_loss_without_double_counting_unobserved_slippage():
    result=financials(pair())
    assert result['gross_at_fill_prices_usdt']==pytest.approx(.05)
    assert result['closed_fees_usdt']==pytest.approx(.20005)
    assert result['net_pnl_usdt']==pytest.approx(-.15005)
    assert result['turnover_usdt']==pytest.approx(200.05)
    assert result['pair_mismatches']==[]
    assert result['cost_provenance']['slippage_cost']['total_usdt'] is None
    assert result['roi'] is None


def test_duplicates_and_accounting_errors_are_not_a_success():
    trades=pair(); trades[1]['net_pnl']=10
    assert financials(trades)['pair_mismatches']
    trades=pair(); trades.append(dict(trades[0], trade_id='duplicate'))
    assert financials(trades)['pair_mismatches'][0]['reason']=='ambiguous_pair'


def test_snapshot_is_read_only_and_does_not_count_proposals_as_trades(tmp_path):
    path=tmp_path/'canonical.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE project_kv(namespace TEXT,item_key TEXT,value_json TEXT,updated_at_ms INT, PRIMARY KEY(namespace,item_key))')
        def put(ns,key,value): db.execute('INSERT INTO project_kv VALUES(?,?,?,?)',(ns,key,json.dumps(value),3))
        for t in pair(): put('paper_trades:test',t['trade_id'],t)
        for ns,key in [('paper_decision_settlements','d'),('self_learning_outcomes_v2','paper:d')]:
            put(ns,key,{'net_pnl':-.15005})
        put('autonomous_paper_state','test',{'cash':100,'equity':100,'positions':{},'realized_pnl':-.15005,'total_fees':.20005})
        put('council_decision_trace','BTCUSDT',{'symbol':'BTCUSDT','status':'PROPOSAL','updated_at_ms':4,'reason':'prospective_edge_unavailable'})
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    result=collect(path,scope='test',since_ms=3,now_ms=5)
    assert result['status']=='VERIFIED' and result['read_only'] is True
    assert result['observation_window']['executions']==0
    assert result['historical_financials']['executions']==2
    assert not result['profitability_proven']
    assert not result['readiness']['registered']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


def test_missing_database_is_not_created(tmp_path):
    path=tmp_path/'missing.db'
    with pytest.raises(sqlite3.OperationalError): collect(path,scope='test',since_ms=0)
    assert not path.exists()
