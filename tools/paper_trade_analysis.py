#!/usr/bin/env python3
"""Read-only diagnostics for canonical autonomous paper trades.

This tool never mutates trading state. It pairs canonical BUY/SELL records,
calculates net-after-fee performance, groups losses by symbol/reason and reports
which agents were associated with losing settlements. V2 remains shadow-only;
its records are reported for comparison and are never promoted by this tool.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime
from typing import Any, Iterable, Mapping

from storage import ProjectDatabase, list_json_items


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _profit_factor(values: Iterable[float]) -> float | None:
    numbers = list(values)
    gross_win = sum(value for value in numbers if value > 0)
    gross_loss = -sum(value for value in numbers if value < 0)
    return None if gross_loss <= 0 else gross_win / gross_loss


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_float(row.get("net_pnl")) for row in rows]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    breakeven = [value for value in pnls if value == 0]
    fees = sum(_float(row.get("total_fees")) for row in rows)
    net = sum(pnls)
    gross_before_fees = net + fees
    return {
        "closed_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate_percent": (len(wins) / len(rows) * 100.0) if rows else None,
        "net_pnl": net,
        "fees": fees,
        "estimated_pnl_before_fees": gross_before_fees,
        "average_net_pnl": (net / len(rows)) if rows else None,
        "average_win": (sum(wins) / len(wins)) if wins else None,
        "average_loss": (sum(losses) / len(losses)) if losses else None,
        "profit_factor": _profit_factor(pnls),
    }


def pair_closed_trades(trades: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pair BUY and SELL records without assuming one global chronology per symbol."""

    unmatched_by_decision: dict[str, deque[Mapping[str, Any]]] = defaultdict(deque)
    unmatched_by_symbol: dict[str, deque[Mapping[str, Any]]] = defaultdict(deque)
    closed: list[dict[str, Any]] = []
    orphan_sells: list[dict[str, Any]] = []

    ordered = sorted(
        (dict(row) for row in trades),
        key=lambda row: (int(row.get("created_at_ms", 0) or 0), str(row.get("trade_id", ""))),
    )

    for trade in ordered:
        side = str(trade.get("side", "")).upper()
        symbol = str(trade.get("symbol", "")).upper()
        decision_id = str(trade.get("decision_id") or "").strip()
        if side == "BUY":
            if decision_id:
                unmatched_by_decision[decision_id].append(trade)
            unmatched_by_symbol[symbol].append(trade)
            continue
        if side != "SELL":
            continue

        buy: Mapping[str, Any] | None = None
        if decision_id and unmatched_by_decision[decision_id]:
            buy = unmatched_by_decision[decision_id].popleft()
            try:
                unmatched_by_symbol[symbol].remove(buy)
            except ValueError:
                pass
        elif unmatched_by_symbol[symbol]:
            buy = unmatched_by_symbol[symbol].popleft()
            buy_decision = str(buy.get("decision_id") or "").strip()
            if buy_decision:
                try:
                    unmatched_by_decision[buy_decision].remove(buy)
                except ValueError:
                    pass

        if buy is None:
            orphan_sells.append(trade)
            continue

        quantity = _float(trade.get("quantity"), _float(buy.get("quantity")))
        entry_price = _float(buy.get("price"))
        exit_price = _float(trade.get("price"))
        entry_fee = _float(buy.get("fee"))
        exit_fee = _float(trade.get("fee"))
        net_pnl = _float(trade.get("net_pnl"))
        notional = entry_price * quantity
        entry_ts = _timestamp(buy.get("time"))
        exit_ts = _timestamp(trade.get("time"))
        settlement = trade.get("decision_settlement") if isinstance(trade.get("decision_settlement"), Mapping) else {}

        closed.append(
            {
                "symbol": symbol,
                "decision_id": decision_id or str(buy.get("decision_id") or ""),
                "candidate_id": str(trade.get("candidate_id") or buy.get("candidate_id") or ""),
                "entry_trade_id": buy.get("trade_id"),
                "exit_trade_id": trade.get("trade_id"),
                "entry_time": buy.get("time"),
                "exit_time": trade.get("time"),
                "holding_seconds": (exit_ts - entry_ts) if entry_ts is not None and exit_ts is not None else None,
                "quantity": quantity,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "entry_reason": buy.get("reason"),
                "exit_reason": trade.get("reason"),
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
                "total_fees": entry_fee + exit_fee,
                "net_pnl": net_pnl,
                "estimated_gross_pnl": net_pnl + entry_fee + exit_fee,
                "net_return_percent": (net_pnl / notional * 100.0) if notional > 0 else None,
                "decision_quality_confidence": buy.get("decision_quality_confidence"),
                "decision_quality_agreement": buy.get("decision_quality_agreement"),
                "general_controller_decision": buy.get("general_controller_decision"),
                "selected_action": settlement.get("selected_action"),
                "realized_action": settlement.get("realized_action"),
                "winning_agents": list(settlement.get("winning_agents") or []),
                "losing_agents": list(settlement.get("losing_agents") or []),
                "abstaining_agents": list(settlement.get("abstaining_agents") or []),
                "reputation_recorded": bool(settlement.get("reputation_recorded")),
            }
        )

    return closed, orphan_sells


def _group(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(row.get(field) or "unknown")].append(row)
    return {
        key: _aggregate(values)
        for key, values in sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))
    }


def _agent_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "winning_settlement_count": 0,
            "losing_settlement_count": 0,
            "abstaining_settlement_count": 0,
            "net_pnl_when_marked_losing": 0.0,
            "net_pnl_when_marked_winning": 0.0,
        }
    )
    for row in rows:
        pnl = _float(row.get("net_pnl"))
        for agent in row.get("winning_agents") or []:
            name = str(agent)
            stats[name]["winning_settlement_count"] += 1
            stats[name]["net_pnl_when_marked_winning"] += pnl
        for agent in row.get("losing_agents") or []:
            name = str(agent)
            stats[name]["losing_settlement_count"] += 1
            stats[name]["net_pnl_when_marked_losing"] += pnl
        for agent in row.get("abstaining_agents") or []:
            stats[str(agent)]["abstaining_settlement_count"] += 1
    return dict(
        sorted(
            stats.items(),
            key=lambda item: (-int(item[1]["losing_settlement_count"]), item[0]),
        )
    )


def analyze_trades(trades: list[Mapping[str, Any]], state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    closed, orphan_sells = pair_closed_trades(trades)
    losses = sorted((row for row in closed if _float(row.get("net_pnl")) < 0), key=lambda row: _float(row.get("net_pnl")))
    wins = sorted((row for row in closed if _float(row.get("net_pnl")) > 0), key=lambda row: _float(row.get("net_pnl")), reverse=True)

    shadow_records = state.get("v2_shadow_records") if isinstance(state, Mapping) else None
    if isinstance(shadow_records, Mapping):
        shadow_rows = [row for row in shadow_records.values() if isinstance(row, Mapping)]
    elif isinstance(shadow_records, list):
        shadow_rows = [row for row in shadow_records if isinstance(row, Mapping)]
    else:
        shadow_rows = []
    challenger = Counter(str(row.get("challenger_action") or "UNKNOWN").upper() for row in shadow_rows)
    champion = Counter(str(row.get("champion_action") or "UNKNOWN").upper() for row in shadow_rows)
    disagreements = sum(
        1
        for row in shadow_rows
        if str(row.get("challenger_action") or "UNKNOWN").upper()
        != str(row.get("champion_action") or "UNKNOWN").upper()
    )
    settled_shadow = sum(1 for row in shadow_rows if row.get("paper_settlement") or row.get("settlement") or row.get("settled_at_ms"))

    summary = _aggregate(closed)
    summary.update(
        {
            "immutable_trade_records": len(trades),
            "buy_records": sum(1 for row in trades if str(row.get("side", "")).upper() == "BUY"),
            "sell_records": sum(1 for row in trades if str(row.get("side", "")).upper() == "SELL"),
            "orphan_sell_records": len(orphan_sells),
        }
    )

    return {
        "summary": summary,
        "by_symbol": _group(closed, "symbol"),
        "by_exit_reason": _group(closed, "exit_reason"),
        "by_entry_reason": _group(closed, "entry_reason"),
        "agent_settlement_associations": _agent_attribution(closed),
        "worst_losses": losses[:10],
        "best_wins": wins[:10],
        "v2_shadow": {
            "records": len(shadow_rows),
            "champion_actions": dict(champion),
            "challenger_actions": dict(challenger),
            "disagreements": disagreements,
            "settled_records": settled_shadow,
            "execution_authority": False,
        },
    }


def _latest_scope(database: ProjectDatabase) -> tuple[str, Mapping[str, Any]]:
    states = list_json_items(database, "autonomous_paper_state", newest_first=True)
    if not states:
        raise RuntimeError("no autonomous_paper_state records found")
    best: tuple[int, str, Mapping[str, Any]] | None = None
    for item in states:
        scope = str(item["key"])
        trade_count = len(list_json_items(database, f"paper_trades:{scope}"))
        candidate = (trade_count, scope, item["value"])
        if best is None or candidate[0] > best[0]:
            best = candidate
    assert best is not None
    return best[1], best[2]


def load_production_analysis(database: ProjectDatabase, *, scope: str | None = None) -> dict[str, Any]:
    if scope:
        state_record = database.get_json("autonomous_paper_state", scope)
        state = state_record["value"] if state_record else {}
        selected_scope = scope
    else:
        selected_scope, state = _latest_scope(database)
    trades = [item["value"] for item in list_json_items(database, f"paper_trades:{selected_scope}")]
    report = analyze_trades(trades, state)
    report["scope"] = selected_scope
    report["database_backend"] = database.backend
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", default=None)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)

    database = ProjectDatabase()
    database.initialize()
    report = load_production_analysis(database, scope=args.scope)
    print(json.dumps(report, ensure_ascii=False, indent=None if args.compact else 2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
