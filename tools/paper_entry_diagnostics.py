"""Bounded chronological PAPER diagnostics, never an alternate portfolio replay.

Consumes an explicit read-only export with ``trades`` and optional immutable
``trade_storage_times``. Screens use only earlier, available baseline closes.
Removed pairs have no replacement fills; retained-pair PnL is not candidate PnL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

COOLDOWN_MINUTES = (15, 30, 60, 120, 240, 360, 720, 1440)
MAX_LEGS = 2000


def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("finite financial evidence required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("finite financial evidence required")
    return result


def metrics(pairs):
    pnl = [p["net_pnl"] for p in sorted(pairs, key=lambda p: p["closed_at_ms"])]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    equity = peak = drawdown = 0.0
    for p in pnl:
        equity += p
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {"closed_pairs": len(pnl), "wins": len(wins), "losses": len(losses),
            "net_pnl_usdt": math.fsum(pnl),
            "expectancy_usdt": math.fsum(pnl) / len(pnl) if pnl else None,
            "profit_factor": math.fsum(wins) / -math.fsum(losses) if losses else None,
            "fees_usdt": math.fsum(p["fees"] for p in pairs),
            "turnover_usdt": math.fsum(p["turnover"] for p in pairs),
            "average_winner_usdt": math.fsum(wins) / len(wins) if wins else None,
            "average_loss_usdt": math.fsum(losses) / len(losses) if losses else None,
            "realized_pair_drawdown_usdt": drawdown,
            "portfolio_max_drawdown_percent": None,
            "drawdown_scope": "closed-pair PnL only; intratrade equity unavailable"}


def diagnose(document):
    trades = document["trades"]
    if not isinstance(trades, list) or len(trades) > MAX_LEGS:
        raise ValueError("explicit export exceeds bounded trade-leg limit")
    stored = document.get("trade_storage_times", {})
    seen, entries, closes, pairs = set(), {}, [], []
    prior_by_entry = {}
    for t in sorted(trades, key=lambda t: (t["created_at_ms"], t["trade_id"])):
        tid, decision, symbol = t["trade_id"], t["decision_id"], t["symbol"]
        if tid in seen or t.get("verified_market_data") is not True:
            raise ValueError("duplicate or unverified trade")
        seen.add(tid)
        at = int(t["created_at_ms"])
        if t["side"] == "BUY":
            if decision in entries:
                raise ValueError("duplicate entry identity")
            entries[decision] = t
            # Equal-time/late-persisted outcomes cannot influence this entry.
            available = [c for c in closes if c["symbol"] == symbol
                         and c["created_at_ms"] < at
                         and int(stored.get(c["trade_id"], c["created_at_ms"])) < at]
            prior_by_entry[decision] = available[-1] if available else None
        elif t["side"] == "SELL":
            entry = entries.get(decision)
            if entry is None or entry["symbol"] != symbol or entry["created_at_ms"] >= at:
                raise ValueError("close lacks prior same-symbol entry; export carry-in explicitly")
            qty, sell_qty = number(entry["quantity"]), number(t["quantity"])
            if qty <= 0 or not math.isclose(qty, sell_qty, rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError("quantity reconciliation failed")
            fees = number(entry["fee"]) + number(t["fee"])
            gross = (number(t["price"]) - number(entry["price"])) * qty
            net = number(t["net_pnl"])
            if not math.isclose(gross - fees, net, rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError("net PnL reconciliation failed")
            pairs.append({"decision_id": decision, "symbol": symbol,
                          "regime": entry.get("regime", "unknown"),
                          "entry_at_ms": entry["created_at_ms"], "closed_at_ms": at,
                          "net_pnl": net, "fees": fees,
                          "turnover": qty * (number(entry["price"]) + number(t["price"])),
                          "exit_reason": t["reason"], "prior_close": prior_by_entry[decision]})
            closes.append(t)
        else:
            raise ValueError("unsupported trade side")
    screens = {}
    for exit_kind in ("protective_stop_loss", "protective_take_profit"):
        for minutes in COOLDOWN_MINUTES:
            removed = [p for p in pairs if p["prior_close"] is not None
                       and p["prior_close"]["reason"] == exit_kind
                       and p["entry_at_ms"] - p["prior_close"]["created_at_ms"] < minutes * 60_000]
            ids = {p["decision_id"] for p in removed}
            retained = [p for p in pairs if p["decision_id"] not in ids]
            screens[f"{exit_kind}:{minutes}m"] = {
                "screened_pairs": len(removed), "retained_baseline_pairs": metrics(retained),
                "screened_wins_losses": dict(Counter("win" if p["net_pnl"] > 0 else "loss" for p in removed)),
                "symbols": {s: metrics([p for p in retained if p["symbol"] == s]) for s in sorted({p["symbol"] for p in pairs})},
                "regimes": {s: metrics([p for p in retained if p["regime"] == s]) for s in sorted({p["regime"] for p in pairs})},
            }
    return {"source_sha256": hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest(),
            "validation_type": "chronological_baseline_pair_screen",
            "baseline": metrics(pairs), "earlier_35": metrics(pairs[:35]),
            "recent_17": metrics(pairs[-17:]), "screens": screens,
            "symbols": {s: metrics([p for p in pairs if p["symbol"] == s]) for s in sorted({p["symbol"] for p in pairs})},
            "regimes": {s: metrics([p for p in pairs if p["regime"] == s]) for s in sorted({p["regime"] for p in pairs})},
            "accounting_reconciled_pairs": len(pairs),
            "profitability_proven": False, "execution_authority": False,
            "limitations": ["No parameter chosen from these screens; both periods are observed diagnostics.",
                            "Prior stops belong to baseline, even when screened out of a candidate.",
                            "No replacement entries, cash/exposure simulation or intratrade drawdown.",
                            "Fill PnL includes spread/slippage/impact; only fees subtracted again."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = diagnose(json.loads(args.evidence.read_text()))
    with args.output.open("x") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({k: result[k] for k in ("validation_type", "baseline", "accounting_reconciled_pairs")}))


if __name__ == "__main__":
    main()
