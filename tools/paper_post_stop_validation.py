"""Chronological paired-trade diagnostic, never an alternate portfolio backtest.

Reads an explicit exported evidence file only. No DB, network, order or runtime
mutation. Historical fills include their original costs; sensitivities add extra
slippage per leg. Delayed replacement entries and candidate drawdown are unknown.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from risk_engine.paper_reentry import PAPER_REENTRY_POLICY_VERSION, post_stop_reentry_block


def _finite(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("financial evidence must be finite numeric data")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("financial evidence must be finite numeric data")
    return parsed


def _metrics(pairs: list[dict[str, Any]], extra_slippage_bps: float) -> dict[str, Any]:
    turnover = sum(pair["turnover"] for pair in pairs)
    pnl = [pair["net_pnl"] - pair["turnover"] * extra_slippage_bps / 10_000 for pair in pairs]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    return {
        "closed_pairs": len(pairs),
        "executions_in_pairs": 2 * len(pairs),
        "net_pnl_of_pairs": sum(pnl),
        "net_expectancy_of_pairs": statistics.mean(pnl) if pnl else None,
        "profit_factor_of_pairs": sum(wins) / -sum(losses) if losses else None,
        "average_loss_of_pairs": statistics.mean(losses) if losses else None,
        "worst_loss_of_pairs": min(pnl) if pnl else None,
        "turnover_of_pairs": turnover,
        "fees_of_pairs": sum(pair["fees"] for pair in pairs),
        "extra_slippage_bps_per_leg": extra_slippage_bps,
        "extra_slippage_cost": turnover * extra_slippage_bps / 10_000,
        "candidate_portfolio_drawdown": None,
    }


def screen_trades(trades: list[dict[str, Any]], *, epoch_start_ms: int) -> dict[str, Any]:
    """Use prior recorded closes to screen entries; label results only afterwards.

    Baseline closes remain baseline facts even if their entry was screened out.
    This deliberate limitation prevents pretending that removed pairs simulate
    the candidate's later cash, holdings, proposals or replacement trades.
    """
    ordered = sorted(trades, key=lambda t: (int(t["created_at_ms"]), str(t["trade_id"])))
    if len({t["trade_id"] for t in ordered}) != len(ordered):
        raise ValueError("duplicate immutable trade identity")
    last_close: dict[str, dict[str, Any]] = {}
    entries: dict[str, dict[str, Any]] = {}
    screened: dict[str, str] = {}
    pairs: list[dict[str, Any]] = []
    for trade in ordered:
        if trade.get("verified_market_data") is not True:
            raise ValueError("unverified trade cannot support validation")
        symbol = str(trade["symbol"])
        timestamp = int(trade["created_at_ms"])
        if timestamp <= 0:
            raise ValueError("positive event timestamp required")
        decision_id = str(trade.get("decision_id") or "")
        if not decision_id:
            raise ValueError("entry decision identity required")
        if trade["side"] == "BUY":
            if decision_id in entries:
                raise ValueError("duplicate entry decision identity")
            entries[decision_id] = trade
            if timestamp >= epoch_start_ms:
                reason = post_stop_reentry_block(last_close.get(symbol), symbol=symbol, now_ms=timestamp)
                if reason:
                    screened[decision_id] = reason
        elif trade["side"] == "SELL":
            net = _finite(trade["net_pnl"])
            last_close[symbol] = {
                "symbol": symbol, "side": "SELL", "trade_id": trade["trade_id"],
                "closed_at_ms": timestamp, "reason": trade["reason"],
                "net_pnl": net, "verified_market_data": True,
            }
            entry = entries.get(decision_id)
            if timestamp < epoch_start_ms:
                continue
            if entry is None or entry["symbol"] != symbol or entry["created_at_ms"] >= timestamp:
                raise ValueError("close cannot be paired to a prior same-symbol entry")
            if int(entry["created_at_ms"]) < epoch_start_ms:
                raise ValueError("epoch crosses an open position; explicit carry-in treatment required")
            fees = _finite(entry["fee"]) + _finite(trade["fee"])
            turnover = sum(_finite(t.get("notional", _finite(t["price"]) * _finite(t["quantity"]))) for t in (entry, trade))
            pairs.append({
                "decision_id": decision_id, "symbol": symbol,
                "entry_at_ms": int(entry["created_at_ms"]), "net_pnl": net,
                "turnover": turnover, "fees": fees, "blocked": decision_id in screened,
            })
        else:
            raise ValueError("PAPER evidence side must be BUY or SELL")
    epoch_entries = sorted(int(t["created_at_ms"]) for t in entries.values() if int(t["created_at_ms"]) >= epoch_start_ms)
    split = epoch_entries[2 * len(epoch_entries) // 3] if epoch_entries else epoch_start_ms
    groups: dict[str, list[dict[str, Any]]] = {
        "full": pairs,
        "earlier": [p for p in pairs if p["entry_at_ms"] < split],
        "later": [p for p in pairs if p["entry_at_ms"] >= split],
    }
    symbols: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        symbols[pair["symbol"]].append(pair)
    groups.update({f"symbol:{symbol}": rows for symbol, rows in symbols.items()})
    comparisons = {}
    for name, rows in groups.items():
        retained = [p for p in rows if not p["blocked"]]
        comparisons[name] = {
            str(bps): {"baseline_pairs": _metrics(rows, bps), "candidate_retained_pairs": _metrics(retained, bps)}
            for bps in (0, 5, 10)
        }
    return {
        "policy_version": PAPER_REENTRY_POLICY_VERSION,
        "validation_type": "chronological_paired_trade_screen",
        "profitability_evidence": "INSUFFICIENT_EVIDENCE",
        "execution_authority": False,
        "live_orders": 0, "testnet_orders": 0,
        "epoch_start_ms": epoch_start_ms,
        "chronological_split_entry_ms": split,
        "untouched_holdout": False,
        "random_time_series_split": False,
        "blocked_entry_reasons": screened,
        "comparisons": comparisons,
        "limitations": [
            "Historical stop facts belong to baseline, including pairs screened out of the candidate.",
            "No replacement-entry, cash, exposure or mark-to-market simulation; candidate drawdown unknown.",
            "Both time partitions were available during diagnosis; fresh PAPER is required for holdout evidence.",
            "Original fills already include modeled spread/slippage; sensitivities are additional per-leg slippage.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--epoch-start-ms", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    evidence = json.loads(args.evidence.read_text())
    result = screen_trades(evidence["trades"], epoch_start_ms=args.epoch_start_ms)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": result["profitability_evidence"], "blocked_entries": len(result["blocked_entry_reasons"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
