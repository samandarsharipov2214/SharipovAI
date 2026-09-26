"""Bounded, read-only canonical PAPER history/cohort reconciliation.

The JSON snapshot cache is never used as lifetime truth. No trading, mutation,
retention, checkpoint, VACUUM, reset or history rewriting occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from storage import ProjectDatabase
from storage.evidence_codec import loads

LIMIT = 20_000


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def economics(trades):
    sells = [t for t in trades if t.get("side") == "SELL"]
    profits = [float(t["net_pnl"]) for t in sells if t.get("net_pnl") is not None]
    wins, losses = [p for p in profits if p > 0], [p for p in profits if p < 0]
    net = math.fsum(profits)
    return {"executions": len(trades), "BUY": sum(t.get("side") == "BUY" for t in trades), "SELL": len(sells),
        "closed": len(profits), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(profits) if profits else None,
        "gross_pnl": math.fsum(float(t.get("gross_pnl") or 0) for t in sells)
            if all(t.get("gross_pnl") is not None for t in sells) else None,
        "fees": math.fsum(float(t.get("fee") or 0) for t in trades),
        "cashflow_usdt": math.fsum((1 if t["side"] == "SELL" else -1)
            * float(t["price"]) * float(t["quantity"]) - float(t["fee"]) for t in trades),
        "spread": math.fsum(float(t.get("spread_cost") or 0) for t in trades),
        "slippage_including_impact": math.fsum(float(t.get("slippage_cost") or 0) for t in trades),
        "net_pnl": net, "expectancy": net / len(profits) if profits else None,
        "profit_factor": math.fsum(wins) / -math.fsum(losses) if losses else None,
        "symbols": sorted({t["symbol"] for t in trades}),
        "first_timestamp_ms": min((t["created_at_ms"] for t in trades), default=None),
        "latest_timestamp_ms": max((t["created_at_ms"] for t in trades), default=None),
        "return_percent": None, "maximum_drawdown_percent": None,
        "limitations": "Return and continuous equity drawdown require cohort capital/equity history; no guessed denominator."}


def capture(database: ProjectDatabase, *, scope: str, since_ms: int = 0) -> dict:
    with database.connect() as connection:
        database._begin(connection)
        try:
            rows = database._fetchall(connection,
                "SELECT namespace,item_key,value_json,updated_at_ms FROM project_kv "
                "WHERE (namespace >= 'paper_trades:' AND namespace < 'paper_trades;') "
                "OR namespace IN ('paper_decision_settlements','self_learning_outcomes_v2',"
                "'autonomous_paper_state','paper_strategy_epochs') ORDER BY namespace,item_key LIMIT ?", (LIMIT + 1,))
        finally:
            connection.rollback()
    if len(rows) > LIMIT:
        raise ValueError("acceptance_source_limit_exceeded")
    trades, settlements, outcomes, states, epochs = [], {}, {}, {}, []
    history = {}
    for row in rows:
        v, ns = loads(row["value_json"]), row["namespace"]
        if ns.startswith("paper_trades:"):
            trades.append({**v, "scope": ns.split(":", 1)[1]})
            history[ns + ":" + row["item_key"]] = sha(v)
        elif ns == "paper_decision_settlements":
            settlements[row["item_key"]] = v
            history[ns + ":" + row["item_key"]] = sha(v)
        elif ns == "self_learning_outcomes_v2":
            outcomes[row["item_key"]] = v
        elif ns == "paper_strategy_epochs":
            epochs.append(v)
        else:
            states[row["item_key"]] = v
    pairs = defaultdict(list)
    for t in trades:
        pairs[(t["scope"], t.get("decision_id") or "missing:" + t["trade_id"])].append(t)
    orphans, mismatches, missing_learning = [], [], []
    closed_ids, cohort_trades = set(), defaultdict(list)
    for (account_scope, decision), group in pairs.items():
        buys = [t for t in group if t["side"] == "BUY"]
        sells = [t for t in group if t["side"] == "SELL"]
        cohort = (buys[0].get("paper_strategy_version", "UNKNOWN_LEGACY") + ":"
                  + buys[0].get("paper_build_sha", "UNKNOWN_LEGACY")) if buys else "ORPHAN"
        cohort_trades[cohort].extend(group)
        if not sells:
            continue
        if len(buys) != 1 or len(sells) != 1:
            orphans.append({"scope": account_scope, "decision_id": decision, "kind": "ambiguous_pair"})
            continue
        buy, sell = buys[0], sells[0]
        closed_ids.add(decision)
        expected = (float(sell["price"]) - float(buy["price"])) * float(buy["quantity"]) - float(buy["fee"]) - float(sell["fee"])
        actual = float(sell["net_pnl"])
        settlement = settlements.get(decision)
        if settlement is None:
            orphans.append({"decision_id": decision, "kind": "missing_settlement"})
        if (not math.isclose(float(buy["quantity"]), float(sell["quantity"]), abs_tol=1e-10)
                or not math.isclose(actual, expected, abs_tol=1e-7)
                or settlement and not math.isclose(actual, float(settlement["net_pnl"]), abs_tol=1e-7)):
            mismatches.append({"decision_id": decision, "actual": actual, "computed": expected,
                               "settled": settlement.get("net_pnl") if settlement else None})
        learned = outcomes.get("paper:" + decision)
        if not learned or not math.isclose(float(learned["net_pnl"]), actual, abs_tol=1e-7):
            missing_learning.append(decision)
    orphans.extend({"decision_id": k, "kind": "orphan_settlement"} for k in settlements if k not in closed_ids)
    active = states.get(scope)
    if active is None:
        raise ValueError("canonical_active_scope_missing")
    active_trades = [t for t in trades if t["scope"] == scope]
    accounting_issues = []
    positions = active.get("positions") or {}
    basis = math.fsum(float(p["quantity"]) * float(p["entry_price"]) for p in positions.values())
    computed_equity = float(active["cash"]) + basis + float(active.get("unrealized_pnl") or 0)
    if not math.isclose(float(active["equity"]), computed_equity, rel_tol=1e-9, abs_tol=1e-6):
        accounting_issues.append("equity_cash_positions_unrealized_mismatch")
    open_ids = {p.get("decision_id") for p in positions.values()}
    unclosed = {decision for (account_scope, decision), group in pairs.items()
                if account_scope == scope and any(t["side"] == "BUY" for t in group)
                and not any(t["side"] == "SELL" for t in group)}
    if open_ids != unclosed:
        accounting_issues.append("open_positions_execution_history_mismatch")
    for field, expected in (("total_fees", math.fsum(float(t.get("fee") or 0) for t in active_trades)),
                            ("realized_pnl", math.fsum(float(t["net_pnl"]) for t in active_trades
                                                      if t.get("side") == "SELL"))):
        if active.get(field) is not None and not math.isclose(float(active[field]), expected, rel_tol=1e-9, abs_tol=1e-6):
            accounting_issues.append(field + "_execution_history_mismatch")
    for key in ("pending_authorized_executions", "pending_protective_executions"):
        if active.get(key):
            accounting_issues.append(key)
    post = [t for t in active_trades if t["created_at_ms"] >= since_ms] if since_ms else []
    result = {"captured_at_ms": int(time.time() * 1000), "scope": scope, "canonical_source": "ProjectDatabase",
        "history_hashes": history, "history_count": len(trades), "settlement_count": len(settlements),
        "history_counts_by_scope": dict(Counter(t["scope"] for t in trades)),
        "lifetime": economics(trades), "active_scope": economics(active_trades),
        "strategy_build_cohorts": {k: economics(v) for k, v in sorted(cohort_trades.items())},
        "new_producer_cohort": economics([t for t in trades if t.get("forecast_evidence")]),
        "post_deploy": economics(post), "orphans": orphans, "pnl_mismatches": mismatches,
        "learning_missing_or_mismatched": missing_learning, "strategy_epochs": epochs,
        "accounting_issues": accounting_issues,
        "account": {k: active.get(k) for k in ("cash", "equity", "realized_pnl", "unrealized_pnl", "total_fees",
            "positions", "pending_authorized_executions", "pending_protective_executions", "last_action", "last_reason",
            "updated_at", "suppressed_wait_events", "paper_rebased_to_initial", "campaign_id")},
        "profitability_gate": "INSUFFICIENT_NEW_PROSPECTIVE_EVIDENCE", "profitability_proven": False}
    return result


def compare(before: dict, after: dict) -> dict:
    old, new = before["history_hashes"], after["history_hashes"]
    missing = [k for k in old if k not in new]
    changed = [k for k in old if k in new and old[k] != new[k]]
    cash_delta = float(after["account"]["cash"]) - float(before["account"]["cash"])
    expected_delta = after["active_scope"]["cashflow_usdt"] - before["active_scope"]["cashflow_usdt"]
    cash_reconciled = before["scope"] == after["scope"] and math.isclose(
        cash_delta, expected_delta, rel_tol=1e-9, abs_tol=1e-6)
    return {"history_preserved": not missing and not changed, "missing": missing, "changed": changed,
            "new_records": len(set(new) - set(old)), "cash_reconciled": cash_reconciled,
            "cash_delta": cash_delta, "execution_cashflow_delta": expected_delta}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--since-ms", type=int, default=0)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = capture(ProjectDatabase(), scope=args.scope, since_ms=args.since_ms)
    if args.before:
        result["comparison"] = compare(json.loads(args.before.read_text()), result)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: result[k] for k in ("history_count", "settlement_count", "orphans", "pnl_mismatches", "post_deploy")}))
    return int(bool(result["orphans"] or result["pnl_mismatches"] or result["accounting_issues"]
                    or result["learning_missing_or_mismatched"]
                    or result.get("comparison", {}).get("cash_reconciled") is False
                    or result.get("comparison", {}).get("history_preserved") is False))


if __name__ == "__main__":
    raise SystemExit(main())
