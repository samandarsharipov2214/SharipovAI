import hashlib
import json
import sqlite3

import pytest

from scripts.astra_paper_audit import collect, financials, reconcile_account


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


@pytest.fixture
def canonical(tmp_path):
    path=tmp_path/'canonical.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE project_kv(namespace TEXT,item_key TEXT,value_json TEXT,updated_at_ms INT, PRIMARY KEY(namespace,item_key))')
        def put(ns,key,value): db.execute('INSERT INTO project_kv VALUES(?,?,?,?)',(ns,key,json.dumps(value),3))
        for t in pair(): put('paper_trades:test',t['trade_id'],t)
        for ns,key in [('paper_decision_settlements','d'),('self_learning_outcomes_v2','paper:d')]:
            put(ns,key,{'net_pnl':-.15005})
        put('autonomous_paper_state','test',{'cash':99.84995,'equity':99.84995,'positions':{},
            'realized_pnl':-.15005,'total_fees':.20005,'unrealized_pnl':0,'configured_initial_cash':100})
        put('council_decision_trace','BTCUSDT',{'symbol':'BTCUSDT','status':'PROPOSAL','updated_at_ms':4,'reason':'prospective_edge_unavailable'})
    return path


def test_snapshot_is_read_only_and_does_not_count_proposals_as_trades(canonical):
    path = canonical
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    result=collect(path,scope='test',since_ms=3,now_ms=5)
    assert result['status']=='VERIFIED' and result['read_only'] is True
    assert result['observation_window']['executions']==0
    assert result['historical_financials']['executions']==2
    assert not result['profitability_proven']
    assert not result['readiness']['registered']
    assert result['capital_reconciliation']['status']=='PASS'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before


@pytest.mark.parametrize('mutation,reason', [
    ({'cash':-1,'equity':-1}, 'negative_cash_or_equity'),
    ({'equity':101}, 'equity_cash_positions_unrealized_mismatch'),
    ({'cash':101,'equity':101}, 'cash_execution_cashflow_mismatch'),
    ({'pending_authorized_executions':{'d':{}}}, 'pending_authorized_executions'),
    ({'pending_protective_executions':{'d':{}}}, 'pending_protective_executions'),
])
def test_impossible_balances_and_unfinished_work_cannot_pass(canonical, mutation, reason):
    with sqlite3.connect(canonical) as db:
        state=json.loads(db.execute("SELECT value_json FROM project_kv WHERE namespace='autonomous_paper_state'").fetchone()[0])
        state.update(mutation)
        db.execute("UPDATE project_kv SET value_json=? WHERE namespace='autonomous_paper_state'",(json.dumps(state),))
    result=collect(canonical,scope='test',since_ms=0)
    assert result['status']=='FAILED' and reason in result['accounting_issues']


@pytest.mark.parametrize('namespace,key', [('paper_decision_settlements','orphan'),('self_learning_outcomes_v2','paper:orphan')])
def test_reverse_linkage_rejects_orphans(canonical,namespace,key):
    with sqlite3.connect(canonical) as db:
        db.execute('INSERT INTO project_kv VALUES(?,?,?,?)',(namespace,key,'{"net_pnl":0}',3))
    result=collect(canonical,scope='test',since_ms=0)
    assert result['status']=='FAILED'
    assert any(v.get('reason')=='orphan_record' for v in result['linkage_mismatches'])


def test_open_position_basis_and_rebased_capital_are_not_guessed():
    trades=pair()[:1]; report=financials(trades)
    state={'cash':99.9,'equity':199.9,'unrealized_pnl':0,'total_fees':.1,'realized_pnl':0,
           'configured_initial_cash':200, 'positions':{'BTCUSDT':{'decision_id':'d','quantity':1,'entry_price':100}}}
    assert reconcile_account(state,trades,report)[0]==[]
    state['positions']['BTCUSDT']['quantity']=2
    assert 'position_execution_mismatch' in reconcile_account(state,trades,report)[0]
    state.update(paper_rebased_to_initial=True)
    assert reconcile_account(state,trades,report)[1]['status']=='NOT_VERIFIED'


def test_missing_database_is_not_created(tmp_path):
    path=tmp_path/'missing.db'
    with pytest.raises(sqlite3.OperationalError): collect(path,scope='test',since_ms=0)
    assert not path.exists()
