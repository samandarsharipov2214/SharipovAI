"""Bounded read-only PAPER audit. Diagnostic completion is not trading approval."""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if '/app' not in sys.path:
    sys.path.insert(0, '/app')

from autonomous_trading.forecast_contract import ARTIFACT_PATH, REVIEWED_MODELS, digest, promotion_failures
from scripts.astra_paper_diagnose import _reason_code
from storage import ProjectDatabase
from storage.evidence_codec import loads

MAX_TRADES = 20_000
MAX_ROW_BYTES = 16 * 1024 * 1024


def financials(trades: list[dict]) -> dict:
    groups = defaultdict(list)
    for trade in trades:
        for key in ('price', 'quantity', 'fee'):
            value = trade[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid_trade_amount:' + key)
        if trade['price'] <= 0 or trade['quantity'] <= 0 or trade['side'] not in {'BUY', 'SELL'}:
            raise ValueError('invalid_trade')
        groups[trade.get('decision_id') or 'missing:' + trade['trade_id']].append(trade)
    mismatches, closed, open_ids = [], [], []
    for decision, group in groups.items():
        buys = [t for t in group if t['side'] == 'BUY']
        sells = [t for t in group if t['side'] == 'SELL']
        if len(buys) == 1 and not sells:
            open_ids.append(decision)
            continue
        if len(buys) != 1 or len(sells) != 1:
            mismatches.append({'decision_id': decision, 'reason': 'ambiguous_pair'})
            continue
        buy, sell = buys[0], sells[0]
        gross = (sell['price'] - buy['price']) * buy['quantity']
        fee = buy['fee'] + sell['fee']
        net = float(sell['net_pnl'])
        if (not math.isfinite(net) or buy['symbol'] != sell['symbol']
                or not math.isclose(buy['quantity'], sell['quantity'], rel_tol=0, abs_tol=1e-10)
                or not math.isclose(gross - fee, net, rel_tol=0, abs_tol=1e-7)):
            mismatches.append({'decision_id': decision, 'reason': 'cashflow_pnl_mismatch'})
            continue
        closed.append({'decision_id': decision, 'gross': gross, 'fees': fee, 'net': net,
                       'at': sell['created_at_ms']})
    profits = [p['net'] for p in closed]
    wins, losses = [p for p in profits if p > 0], [p for p in profits if p < 0]
    curve = peak = drawdown = 0.
    for trade in sorted(closed, key=lambda t: (t['at'], t['decision_id'])):
        curve += trade['net']; peak = max(peak, curve); drawdown = max(drawdown, peak - curve)
    costs = {}
    for field in ('slippage_cost', 'spread_cost'):
        values = [t[field] for t in trades if t.get(field) is not None]
        costs[field] = {'observed_records': len(values), 'total_records': len(trades),
                        'total_usdt': math.fsum(values) if len(values) == len(trades) else None}
    return {'executions': len(trades), 'sides': dict(Counter(t['side'] for t in trades)),
            'closed_pairs': len(closed), 'gross_at_fill_prices_usdt': math.fsum(t['gross'] for t in closed),
            'closed_fees_usdt': math.fsum(t['fees'] for t in closed),
            'all_execution_fees_usdt': math.fsum(t['fee'] for t in trades),
            'net_pnl_usdt': math.fsum(profits),
            'turnover_usdt': math.fsum(t['price'] * t['quantity'] for t in trades),
            'wins': len(wins), 'losses': len(losses), 'win_rate': len(wins)/len(profits) if profits else None,
            'expectancy_usdt': math.fsum(profits)/len(profits) if profits else None,
            'profit_factor': math.fsum(wins)/-math.fsum(losses) if losses else None,
            'closed_net_pnl_drawdown_usdt': drawdown, 'cost_provenance': costs,
            'roi': None, 'equity_drawdown_percent': None,
            'limitations': 'Fill prices already include any modeled spread/slippage. Do not subtract them twice. '
                           'ROI and equity drawdown require complete capital/rebase and mark-to-market history.',
            'pair_mismatches': mismatches, 'open_decision_ids': sorted(open_ids), 'closed': closed}


def collect(path: Path, *, scope: str, since_ms: int, now_ms: int | None = None) -> dict:
    now_ms = int(time.time()*1000) if now_ms is None else now_ms
    deadline = time.monotonic() + 15
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2) as db:
        db.execute('PRAGMA query_only=ON')
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        db.execute('BEGIN')
        def record(namespace, key):
            row = db.execute('SELECT value_json FROM project_kv WHERE namespace=? AND item_key=?',
                             (namespace, key)).fetchone()
            if row and len(row[0]) > MAX_ROW_BYTES:
                raise ValueError('audit_row_limit')
            return loads(row[0]) if row else None
        trades = []
        for row in db.execute('SELECT value_json FROM project_kv WHERE namespace=? ORDER BY item_key LIMIT ?',
                              ('paper_trades:' + scope, MAX_TRADES+1)):
            if len(trades) >= MAX_TRADES or len(row[0]) > MAX_ROW_BYTES:
                raise ValueError('audit_source_limit')
            trades.append(loads(row[0]))
        state = record('autonomous_paper_state', scope)
        if state is None:
            raise ValueError('canonical_scope_missing')
        report = financials(trades)
        linkage = []
        for t in report['closed']:
            for namespace, key in (('paper_decision_settlements', t['decision_id']),
                                   ('self_learning_outcomes_v2', 'paper:' + t['decision_id'])):
                row = record(namespace, key)
                if not row or not math.isclose(float(row.get('net_pnl', math.inf)), t['net'], rel_tol=0, abs_tol=1e-7):
                    linkage.append({'decision_id': t['decision_id'], 'namespace': namespace})
        del report['closed']
        accounting = []
        for field, computed in [('realized_pnl', report['net_pnl_usdt']), ('total_fees', report['all_execution_fees_usdt'])]:
            if not math.isclose(float(state.get(field, math.inf)), computed, rel_tol=1e-9, abs_tol=1e-6):
                accounting.append(field + '_mismatch')
        if set(report['open_decision_ids']) != {p.get('decision_id') for p in (state.get('positions') or {}).values()}:
            accounting.append('open_positions_mismatch')
        traces = []
        for key, _ in db.execute('SELECT item_key,updated_at_ms FROM project_kv WHERE namespace=? LIMIT 33',
                                ('council_decision_trace',)):
            if len(traces) >= 32: raise ValueError('audit_symbol_limit')
            t = record('council_decision_trace', key)
            traces.append({**{k:t.get(k) for k in ('symbol','phase','updated_at_ms','reason','turnover_usdt',
                'min_turnover_usdt','change_24h_percent','entry_change_percent','quote_age_ms','market_verified')},
                'reason_code': _reason_code(t), 'observation_age_ms': now_ms-int(t.get('updated_at_ms') or 0)})
        readiness = record('paper_forecast_readiness', 'plan')
        db.rollback()
    artifact = json.loads(ARTIFACT_PATH.read_text())
    recent = [t for t in trades if since_ms <= t['created_at_ms'] <= now_ms]
    return {'status': 'FAILED' if report['pair_mismatches'] or linkage or accounting else 'VERIFIED',
            'read_only': True, 'generated_at_ms': now_ms, 'scope': scope,
            'audit_completed': True, 'profitability_proven': False, 'historical_financials': report,
            'linkage_mismatches': linkage, 'accounting_issues': accounting,
            'account': {k:state.get(k) for k in ('cash','equity','configured_initial_cash','paper_rebased_to_initial',
                        'positions','pending_authorized_executions','pending_protective_executions')},
            'observation_window': {'since_ms': since_ms, 'until_ms': now_ms, 'executions': len(recent),
                                  'buys': sum(t['side']=='BUY' for t in recent), 'sells': sum(t['side']=='SELL' for t in recent)},
            'current_decisions': traces,
            'forecast': {'reviewed': digest(artifact) in REVIEWED_MODELS,
                         'promotion_failures': promotion_failures(artifact['validation']),
                         'stored_test_directional_accuracy': artifact['validation'].get('test',{}).get('directional_accuracy'),
                         'note': 'Existing consumed evaluation; no new OOS evaluation performed.'},
            'readiness': {'registered': readiness is not None,
                          'holdout_end_ms': readiness.get('holdout_end_ms') if readiness else None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope')
    args = parser.parse_args()
    cfg = ProjectDatabase()  # Configuration only; never initialize or open a writable connection.
    if cfg.backend != 'sqlite': raise ValueError('read_only_audit_requires_sqlite')
    scope = args.scope or json.loads((Path(__file__).resolve().parents[1]/'docs/paper-next-model-specification.json').read_text())['scope']
    result = collect(Path(cfg.dsn.removeprefix('sqlite:///')), scope=scope, since_ms=int(time.time()*1000)-86400000)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] == 'VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
