"""Offline retrospective quote diagnostics owned by Learning Engine.

These are fixed-horizon one-unit long markouts, not fills, expected returns or
portfolio replay. Entry ask and future bid include spread exactly once. Frozen
entry-time fees and base slippage are charged on each leg. Depth, size, tick/lot
rounding and market impact remain unknown; no complete net expectancy is claimed.
Nothing here reads a database, fits a predictor, changes policy or submits orders.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

HORIZONS_SECONDS = (300, 900, 1800, 3600, 14400)
QUOTE_MAX_AGE_MS = 2000
LABEL_TOLERANCE_MS = 10_000
NON_DIRECTIONAL = {"decision_quality", "risk_engine", "portfolio_engine", "security_guard"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _timestamp(value: Any) -> int:
    number = _number(value)
    if number is None or number <= 0 or not number.is_integer():
        raise ValueError("timestamps must be positive integral milliseconds")
    return int(number)


def _quote(row: Mapping[str, Any]) -> tuple[float, float, int] | None:
    quote = row.get("quote")
    if row.get("market_verified") is not True or not isinstance(quote, Mapping):
        return None
    bid, ask, at = (_number(quote.get(k)) for k in
                    ("bid_price", "ask_price", "received_at_unix_ms"))
    if (None in (bid, ask, at) or not 0 < bid <= ask or at <= 0
            or not at.is_integer() or not 0 <= row["decision_time_ms"] - at <= QUOTE_MAX_AGE_MS):
        return None
    return bid, ask, int(at)


def _cost(row: Mapping[str, Any]) -> tuple[float, float] | None:
    model = row.get("cost_model")
    if not isinstance(model, Mapping):
        return None
    fee, bps = (_number(model.get(k)) for k in ("fee_rate", "slippage_bps"))
    if fee is None or bps is None or not 0 <= fee < 1 or not 0 <= bps < 10_000:
        return None
    return fee, bps / 10_000


def _signals(row: Mapping[str, Any]) -> dict[str, str]:
    signals = {}
    for opinion in (row.get("council") or {}).get("opinions", []):
        agent, action = opinion.get("agent_id"), opinion.get("action")
        verified = opinion.get("verified_market_data") is True or opinion.get("data_verified") is True
        if agent and agent not in NON_DIRECTIONAL and verified and action in {"BUY", "SELL", "WAIT"}:
            if agent in signals:
                raise ValueError("duplicate Council member in one opportunity")
            signals[agent] = action
    if signals:
        score = sum({"BUY": 1, "SELL": -1, "WAIT": 0}[v] for v in signals.values())
        signals["EQUAL_WEIGHT_DIRECTION"] = "BUY" if score > 0 else "SELL" if score < 0 else "WAIT"
    dq = (row.get("decision_quality") or {}).get("decision_quality_action")
    if dq in {"BUY", "SELL", "WAIT"}:
        signals["DQ_PREBRIDGE_INTENT"] = dq
    return signals


def _mean(values: list[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [r for r in records if r["status"] == "OBSERVED"]
    names = sorted({name for r in records for name in r["signals"]})
    signals = {}
    for name in names:
        available = [r for r in observed if name in r["signals"]]
        buys = [r for r in available if r["signals"][name] == "BUY"]
        calls = [r for r in available if r["signals"][name] in {"BUY", "SELL"}
                 and r["midpoint_change_percent"] != 0]
        signals[name] = {
            "selected_anchors_with_signal": sum(name in r["signals"] for r in records),
            "observed_labels_with_signal": len(available),
            "actions_on_observed_labels": dict(Counter(r["signals"][name] for r in available)),
            "directional_nonflat_labels": len(calls),
            "direction_hit_rate": _mean([float((1 if r["signals"][name] == "BUY" else -1)
                                                * r["midpoint_change_percent"] > 0) for r in calls]),
            "buy_labels": len(buys),
            "buy_mean_midpoint_change_percent": _mean([r["midpoint_change_percent"] for r in buys]),
            "buy_mean_long_markout_percent_excluding_impact": _mean([
                r["long_markout_percent_excluding_impact"] for r in buys]),
            "buy_positive_markouts": sum(r["long_markout_percent_excluding_impact"] > 0 for r in buys),
            "sell_executable_return_percent": None,
            "net_expectancy": None,
        }
    return {"selected_anchors": len(records), "coverage": dict(Counter(r["status"] for r in records)),
            "signals": signals, "independent_sample_size": None,
            "cash_only_reference_markout_percent": 0.0 if observed else None,
            "portfolio_net_expectancy": None, "profit_factor": None}


def _abstention_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe quote outcomes after actual actions, without counterfactual fills."""
    groups = defaultdict(list)
    for record in records:
        proposal = record["proposal_present"]
        population = ("proposal" if proposal is True else "no_proposal" if proposal is False
                      else "proposal_status_unknown")
        groups[(population, record["actual_paper_status"] or "UNKNOWN")].append(record)
    result = []
    for (population, action), members in sorted(groups.items()):
        values = [r["long_markout_percent_excluding_impact"] for r in members if r["status"] == "OBSERVED"]
        result.append({"population": population, "actual_paper_status": action,
            "selected_anchors": len(members), "coverage": dict(Counter(r["status"] for r in members)),
            "observed_labels": len(values), "mean_long_markout_percent_excluding_impact": _mean(values),
            "positive_long_markouts": sum(v > 0 for v in values) if values else None,
            "worst_long_markout_percent_excluding_impact": min(values) if values else None,
            "portfolio_counterfactual_net_pnl": None})
    return {"groups": result,
            "interpretation": "Quoted long paths after recorded actions; WAIT profitability, missed executable trades and available capital are not established."}


def fixed_horizon_markouts(
    rows: Sequence[Mapping[str, Any]], *, cutoff_ms: int,
    horizons_seconds: Sequence[int] = HORIZONS_SECONDS,
    anchor_population: str = "proposals",
) -> dict[str, Any]:
    """Label chronological anchors per symbol before outcome checks.

    The default selects proposals. Explicit all_opportunities also includes
    WAIT/no-proposal records, retaining their actual action and signal absence.
    The next anchor reserves the whole horizon plus quote tolerance, even when
    the first anchor lacks a quote/cost/label. Do not replace missing outcomes
    with later successful observations. Cross-symbol dependence remains.
    Both entry and label persistence must be available by the explicit cutoff.
    A SELL opinion is a directional label only, never a fabricated spot short.
    """
    if anchor_population not in {"proposals", "all_opportunities"}:
        raise ValueError("anchor_population must be proposals or all_opportunities")
    cutoff = _timestamp(cutoff_ms)
    horizons = tuple(horizons_seconds)
    if (not horizons or any(isinstance(h, bool) or not isinstance(h, int) or h <= 0 for h in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError("horizons must be distinct positive integer seconds")
    ids = set()
    available = []
    for row in rows:
        for key in ("opportunity_id", "scope", "symbol"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("opportunity identity, scope and symbol are required")
        if row["opportunity_id"] in ids:
            raise ValueError("duplicate opportunity identity")
        ids.add(row["opportunity_id"])
        at, stored = _timestamp(row.get("decision_time_ms")), _timestamp(row.get("recorded_at_ms"))
        if stored < at:
            raise ValueError("opportunity persistence precedes decision")
        if stored <= cutoff:
            available.append(row)
    available.sort(key=lambda r: (r["decision_time_ms"], r["opportunity_id"]))
    groups = defaultdict(list)
    for row in available:
        quote = _quote(row)
        if quote is not None:
            groups[(row["scope"], row["symbol"])].append((quote[2], row["recorded_at_ms"], row["opportunity_id"], row))
    for quotes in groups.values():
        quotes.sort(key=lambda item: item[:3])
    times = {key: [item[0] for item in values] for key, values in groups.items()}
    records = []
    for horizon in horizons:
        next_at = {}
        for row in available:
            key, at = (row["scope"], row["symbol"]), row["decision_time_ms"]
            if ((anchor_population == "proposals" and row.get("proposal_present") is not True)
                    or at < next_at.get(key, 0)):
                continue
            target = at + horizon * 1000
            next_at[key] = target + LABEL_TOLERANCE_MS + 1
            record = {"opportunity_id": row["opportunity_id"], "scope": row["scope"], "symbol": row["symbol"],
                      "decision_time_ms": at, "entry_available_at_ms": row["recorded_at_ms"],
                      "paper_build_sha": row.get("paper_build_sha"), "strategy_epoch_id": row.get("strategy_epoch_id"),
                      "regime": row.get("regime"), "horizon_seconds": horizon, "signals": _signals(row),
                      "actual_paper_status": (row.get("result") or {}).get("status"),
                      "status": "MISSING_FUTURE_QUOTE", "complete_net_return_percent": None}
            if anchor_population == "all_opportunities":
                record["proposal_present"] = row.get("proposal_present")
                record["actual_paper_phase"] = (row.get("result") or {}).get("phase")
            records.append(record)
            entry, cost = _quote(row), _cost(row)
            if entry is None:
                record["status"] = "INVALID_ENTRY_QUOTE"
                continue
            if cost is None:
                record["status"] = "ENTRY_COST_UNAVAILABLE"
                continue
            if target > cutoff:
                record["status"] = "HORIZON_NOT_ELAPSED"
                continue
            index = bisect.bisect_left(times.get(key, []), target)
            quotes = groups.get(key, [])
            if index == len(quotes) or quotes[index][0] > target + LABEL_TOLERANCE_MS:
                continue
            future = quotes[index][3]
            exit_bid, exit_ask, received = _quote(future)
            entry_bid, entry_ask, _ = entry
            fee, slippage = cost
            entry_price = entry_ask * (1 + slippage)
            exit_price = exit_bid * (1 - slippage)
            entry_fee, exit_fee = entry_price * fee, exit_price * fee
            cash_paid, cash_received = entry_price + entry_fee, exit_price - exit_fee
            record.update({"status": "OBSERVED", "label_opportunity_id": future["opportunity_id"],
                "label_quote_time_ms": received, "label_available_at_ms": future["recorded_at_ms"],
                "horizon_offset_ms": received - target,
                "midpoint_change_percent": 100 * ((exit_bid + exit_ask) / (entry_bid + entry_ask) - 1),
                "bbo_long_markout_percent_before_fees_slippage": 100 * (exit_bid / entry_ask - 1),
                "long_markout_percent_excluding_impact": 100 * (cash_received / cash_paid - 1),
                "unit_cashflows": {"entry_ask": entry_ask, "exit_bid": exit_bid,
                    "entry_price_with_base_slippage": entry_price, "exit_price_with_base_slippage": exit_price,
                    "entry_fee": entry_fee, "exit_fee": exit_fee,
                    "cash_paid": cash_paid, "cash_received": cash_received,
                    "fee_rate_frozen_at_entry": fee, "slippage_fraction_frozen_at_entry": slippage,
                    "market_impact": None}})
    report = {"schema_version": 1, "owner": "learning_engine", "cutoff_ms": cutoff,
        "source_rows": len(rows), "available_source_rows": len(available),
        "source_sha256": hashlib.sha256(json.dumps(list(rows), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "horizons": {str(h): _summary([r for r in records if r["horizon_seconds"] == h]) for h in horizons},
        "records": records, "execution_authority": False, "policy_influence": "NONE",
        "profitability_evidence": "INSUFFICIENT_EVIDENCE",
        "limitations": ["Retrospective diagnostics, not forecasts, fills, portfolio replay or untouched holdout.",
            "Entry ask and future bid charge spread once; entry-time fee/slippage assumptions are frozen for both legs.",
            "Quantity-dependent impact, executable depth, rounding, inventory and capital constraints are not modeled.",
            "Anchors are chosen before quote, cost and outcome checks; missing anchors are retained.",
            "BUY summaries are conditional on available labels; compare coverage and actions before comparing models.",
            "SELL is direction only. The cash reference is isolated zero-yield cash, not the existing PAPER portfolio.",
            "Same-symbol intervals do not overlap; symbols and shared evidence may still be correlated."]}
    if anchor_population == "all_opportunities":
        report["anchor_population"] = anchor_population
        report["abstention_diagnostics"] = {str(h): _abstention_summary([
            r for r in records if r["horizon_seconds"] == h]) for h in horizons}
        report["limitations"].append("All-opportunity anchors include missing proposals; absent Council/DQ opinions are not fabricated WAIT votes.")
    return report
