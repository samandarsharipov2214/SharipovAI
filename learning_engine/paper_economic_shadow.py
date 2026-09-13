"""As-of PAPER economics for research. No forecasting or execution authority.

Fill-price PnL already includes spread/slippage/impact. Only pair fees are
subtracted from fill-price gross PnL; those execution costs are never charged
twice. A descriptive historical mean is never promoted to expected return.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from typing import Any, Mapping

from storage import ProjectDatabase

VERSION = "paper-economic-shadow-v1"
UNKNOWN_EPOCH = "UNKNOWN_LEGACY_EPOCH"
SOURCE_LIMIT = 20_000


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_sources(database: ProjectDatabase, scope: str, *, asof_ms: int | None = None) -> dict[str, Any]:
    """One bounded canonical database snapshot; never silently truncate support."""
    namespaces = (f"paper_trades:{scope}", "self_learning_outcomes_v2", "paper_strategy_epochs",
                  "paper_policy_equivalence")
    with database.connect() as connection:
        database._begin(connection)
        rows = database._fetchall(connection,
            "SELECT namespace,item_key,value_json,updated_at_ms FROM project_kv "
            "WHERE namespace IN (?,?,?,?) AND updated_at_ms < ? ORDER BY namespace,item_key LIMIT ?",
            (*namespaces, int(time.time() * 1000) + 1 if asof_ms is None else asof_ms, SOURCE_LIMIT + 1))
        connection.rollback()
    if len(rows) > SOURCE_LIMIT:
        return {"coverage": "SOURCE_LIMIT_EXCEEDED", "trades": [], "outcomes": {}, "epochs": [], "policy_links": []}
    result: dict[str, Any] = {"coverage": "COMPLETE_SNAPSHOT", "trades": [], "outcomes": {}, "epochs": [], "policy_links": []}
    for row in rows:
        document = {"value": json.loads(row["value_json"]), "stored_at_ms": int(row["updated_at_ms"])}
        if row["namespace"] == namespaces[0]:
            result["trades"].append(document)
        elif row["namespace"] == namespaces[1]:
            result["outcomes"][row["item_key"]] = document
        elif row["namespace"] == namespaces[2]:
            result["epochs"].append(document)
        else:
            result["policy_links"].append(document)
    return result


def _epoch(epochs: list, *, scope: str, at_ms: int, build: str, policy: str,
           known_by_ms: int) -> str:
    matches = [row["value"] for row in epochs
               if row["stored_at_ms"] < known_by_ms
               and row["value"].get("scope") == scope
               and row["value"].get("sha") == build
               and row["value"].get("strategy_version") == policy
               and 0 < int(row["value"].get("epoch_start_ms") or 0) <= at_ms]
    if not matches:
        return UNKNOWN_EPOCH
    # The latest registered boundary is authoritative; no guessed old provenance.
    latest = max(matches, key=lambda item: int(item["epoch_start_ms"]))
    return str(latest["epoch_id"])


def _stats(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    values = [row["net_pnl"] for row in rows]
    wins, losses = [p for p in values if p > 0], [p for p in values if p < 0]
    return {
        "sample_size": n, "wins": len(wins), "losses": len(losses),
        "net_pnl": math.fsum(values),
        "historical_net_expectancy_usdt": math.fsum(values) / n if n else None,
        "historical_gross_fill_expectancy_usdt": math.fsum(r["gross_fill_pnl"] for r in rows) / n if n else None,
        "mean_pair_fees_usdt": math.fsum(r["pair_fees"] for r in rows) / n if n else None,
        "historical_mean_net_return_percent": math.fsum(r["net_return_percent"] for r in rows) / n if n else None,
        "average_win": math.fsum(wins) / len(wins) if wins else None,
        "average_loss": math.fsum(losses) / len(losses) if losses else None,
        "worst_loss": min(losses) if losses else None,
        "profit_factor": math.fsum(wins) / -math.fsum(losses) if losses else None,
        "statistic_role": "DESCRIPTIVE_CLOSED_TRADE_COHORT_NOT_FORECAST",
    }


def _policy_cohort(sources: Mapping[str, Any], matched: list[dict], *,
                   epoch_id: str, scope: str, regime: str, at_ms: int) -> dict | None:
    """Optional descriptive continuity, never inferred from a version string.

    An immutable, separately verified equivalence record must target the current
    observation epoch. Its evidence digest attests reviewed entry/exit behavior
    and configuration equivalence; unchanged core policy/risk/cost versions are
    also checked here. Registering such evidence cannot change an earlier input.
    The original build cohort and all forecast/authority outputs stay unchanged.
    """
    links = [r for r in sources.get("policy_links", [])
             if r["stored_at_ms"] < at_ms and isinstance(r.get("value"), Mapping)
             and r["value"].get("scope") == scope
             and r["value"].get("observation_epoch_id") == epoch_id
             and epoch_id != UNKNOWN_EPOCH]
    if not links:
        return None
    result = {"status": "INVALID_EQUIVALENCE", "cohort": None,
              "support_status": "INSUFFICIENT_EVIDENCE", "execution_authority": False,
              "policy_influence": "SHADOW_ONLY"}
    if sources.get("coverage") != "COMPLETE_SNAPSHOT":
        return {**result, "status": "INCOMPLETE_SOURCE"}
    if len(links) != 1:
        return {**result, "status": "AMBIGUOUS_EQUIVALENCE"}
    link, stored = links[0]["value"], links[0]["stored_at_ms"]
    members, evidence = link.get("epoch_ids"), link.get("verification_sha256")
    if (type(link.get("schema_version")) is not int or link["schema_version"] != 1 or link.get("status") != "verified"
            or link.get("policy_changed") is not False or link.get("risk_budget_changed") is not False
            or link.get("configuration_unchanged") is not True or link.get("entry_exit_policy_unchanged") is not True
            or not isinstance(evidence, str) or len(evidence) != 64
            or any(c not in "0123456789abcdef" for c in evidence)
            or not isinstance(members, list) or len(members) < 2
            or any(not isinstance(v, str) or not v or v == UNKNOWN_EPOCH for v in members)
            or len(set(members)) != len(members) or epoch_id not in members
            or link.get("policy_evaluation_id") not in members):
        return result
    epochs = [r["value"] for r in sources["epochs"] if r["stored_at_ms"] <= stored
              and r["value"].get("scope") == scope and r["value"].get("epoch_id") in members]
    if len(epochs) != len(members) or {e["epoch_id"] for e in epochs} != set(members):
        return result
    if any((start := finite(e.get("epoch_start_ms"))) is None or not 0 < start <= at_ms for e in epochs):
        return result
    for field in ("strategy_version", "decision_policy_version", "risk_version", "cost_model_version"):
        values = [e.get(field) for e in epochs]
        if not all(isinstance(v, str) and v.strip() for v in values) or len(set(values)) != 1:
            return result
    eligible, lineage = [], []
    excluded_exit_policy = 0
    # matched already contains only unique, reconciled, as-of BUY/SELL pairs.
    # Resolve the SELL's build independently: an equivalent entry does not
    # establish that a later exit ran under the same verified policy.
    sells = {r["value"].get("trade_id"): r["value"] for r in sources["trades"]
             if r["value"].get("side") == "SELL" and r["stored_at_ms"] < at_ms}
    for row in matched:
        if (row["entry_epoch"] not in members or regime.lower() in {"unknown", "", "none"}
                or row["regime"] != regime):
            continue
        sell = sells.get(row["trade_id"], {})
        exit_epoch = _epoch(sources["epochs"], scope=scope, at_ms=row["closed_at_ms"],
            build=str(sell.get("paper_build_sha") or "unknown"),
            policy=str(sell.get("paper_strategy_version") or "unknown"), known_by_ms=at_ms)
        if exit_epoch not in members:
            excluded_exit_policy += 1
            continue
        eligible.append(row)
        lineage.append({"outcome_id": row["outcome_id"], "entry_epoch_id": row["entry_epoch"],
                        "exit_policy_epoch_id": exit_epoch})
    return {**result, "status": "VERIFIED_EQUIVALENCE_DESCRIPTIVE_ONLY",
        "policy_evaluation_id": link["policy_evaluation_id"], "observation_epoch_id": epoch_id,
        "entry_epoch_ids": sorted(members), "verification_sha256": evidence,
        "equivalence_available_at_ms": stored, "cohort": _stats(eligible),
        "trade_epoch_lineage": lineage, "excluded_exit_policy_count": excluded_exit_policy,
        "evidence_outcome_ids": [r["outcome_id"] for r in eligible],
        "evidence_digest": digest([r["source_digest"] for r in eligible]),
        "forecast_role": "NOT_A_FORECAST; original build cohort and edge support remain separately reported"}


def assess_opportunity(opportunity: Mapping[str, Any], sources: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly exclude outcomes/ingestion at or after the captured decision time.

    Computation may run later on the observer worker. Both source availability
    AND physical Learning-record ingestion must precede the decision. Unknown
    epochs/regimes do not qualify as a matching predictive cohort.
    """
    at = int(opportunity["decision_time_ms"])
    scope, symbol = str(opportunity["scope"]), str(opportunity["symbol"])
    regime = str(opportunity.get("regime") or "unknown")
    epoch_id = _epoch(sources["epochs"], scope=scope, at_ms=at,
        build=str(opportunity.get("paper_build_sha") or "unknown"),
        policy=str(opportunity.get("paper_strategy_version") or "unknown"), known_by_ms=at)
    pairs: dict[str, list] = defaultdict(list)
    rejected: Counter = Counter()
    for row in sources["trades"]:
        trade = row["value"]
        if (trade.get("symbol") == symbol and row["stored_at_ms"] < at
            and 0 < int(trade.get("created_at_ms") or 0) < at):
            pairs[str(trade.get("decision_id") or "")].append(row)
    matched = []
    for decision, pair in pairs.items():
        buys = [r for r in pair if r["value"].get("side") == "BUY"]
        sells = [r for r in pair if r["value"].get("side") == "SELL"]
        if not sells:
            continue
        if not decision or len(buys) != 1 or len(sells) != 1:
            rejected["ambiguous_pair"] += 1
            continue
        buy_row, sell_row = buys[0], sells[0]
        buy, sell = buy_row["value"], sell_row["value"]
        outcome_row = sources["outcomes"].get("paper:" + decision)
        if (not outcome_row or outcome_row["stored_at_ms"] >= at
            or max(int(outcome_row["value"].get("occurred_at_ms") or 0),
                   int(outcome_row["value"].get("evidence_available_at_ms") or 0)) >= at):
            rejected["missing_asof_learning_outcome"] += 1
            continue
        outcome = outcome_row["value"]
        times = [int(buy.get("created_at_ms") or 0), int(sell.get("created_at_ms") or 0),
                 int(outcome.get("occurred_at_ms") or 0), int(outcome.get("evidence_available_at_ms") or 0)]
        if not (0 < times[0] <= times[1] <= times[2] <= times[3]):
            rejected["invalid_chronology"] += 1
            continue
        available = max(*times, buy_row["stored_at_ms"], sell_row["stored_at_ms"], outcome_row["stored_at_ms"])
        if available >= at:
            rejected["not_available_at_decision"] += 1
            continue
        if (outcome.get("evidence_schema_version") != 2 or outcome.get("source") != "paper"
            or outcome.get("decision_id") != decision or outcome.get("outcome_id") != "paper:" + decision
            or any(v.get("verified_market_data") is not True for v in (buy, sell, outcome))):
            rejected["unverified_or_wrong_source"] += 1
            continue
        bprice, sprice, bqty, sqty, bfee, sfee, pnl, learning_pnl = map(finite,
            (buy.get("price"), sell.get("price"), buy.get("quantity"), sell.get("quantity"),
             buy.get("fee"), sell.get("fee"), sell.get("net_pnl"), outcome.get("net_pnl")))
        if (None in (bprice, sprice, bqty, sqty, bfee, sfee, pnl, learning_pnl)
            or min(bprice, sprice, bqty, sqty) <= 0 or min(bfee, sfee) < 0
            or not math.isclose(bqty, sqty, rel_tol=1e-10, abs_tol=1e-12)):
            rejected["invalid_fill_units"] += 1
            continue
        gross = (sprice - bprice) * bqty
        if not (math.isclose(gross - bfee - sfee, pnl, rel_tol=1e-8, abs_tol=1e-8)
                and math.isclose(pnl, learning_pnl, rel_tol=1e-10, abs_tol=1e-10)):
            rejected["accounting_mismatch"] += 1
            continue
        entry_epoch = _epoch(sources["epochs"], scope=scope, at_ms=times[0],
            build=str(buy.get("paper_build_sha") or "unknown"),
            policy=str(buy.get("paper_strategy_version") or "unknown"), known_by_ms=at)
        matched.append({"outcome_id": outcome["outcome_id"], "decision_id": decision,
            "entry_epoch": entry_epoch, "regime": str(outcome.get("regime") or "unknown"),
            "net_pnl": pnl, "gross_fill_pnl": gross, "pair_fees": bfee + sfee,
            "net_return_percent": 100 * pnl / (bprice * bqty), "closed_at_ms": times[1],
            "available_at_ms": available, "exit_reason": str(sell.get("reason") or "unknown"),
            "trade_id": sell.get("trade_id"), "source_digest": digest([buy, sell, outcome])})
    matched.sort(key=lambda row: (row["available_at_ms"], row["outcome_id"]))
    eligible = [r for r in matched if epoch_id != UNKNOWN_EPOCH and r["entry_epoch"] == epoch_id
                and regime.lower() not in {"unknown", "", "none"} and r["regime"] == regime]
    last_stop = next((r for r in reversed(sorted(matched, key=lambda r: r["closed_at_ms"]))
                     if r["exit_reason"].startswith("protective_stop_loss")), None)
    context = {"version": VERSION, "scope": scope, "symbol": symbol, "regime": regime,
        "strategy_epoch_id": epoch_id, "cohort": _stats(eligible),
        "evidence_outcome_ids": [r["outcome_id"] for r in eligible],
        "evidence_digest": digest([r["source_digest"] for r in eligible]),
        "recent_failed_hypothesis": last_stop,
        "same_symbol_prior_reconciled_closes": len(matched),
        "support_status": "INSUFFICIENT_EVIDENCE", "confidence_adjustment": None,
        "execution_authority": False, "policy_influence": "SHADOW_ONLY"}
    policy_cohort = _policy_cohort(sources, matched, epoch_id=epoch_id,
                                    scope=scope, regime=regime, at_ms=at)
    if policy_cohort is not None:
        context["policy_cohort"] = policy_cohort
    quote = opportunity.get("quote") or {}
    bid, ask = finite(quote.get("bid_price")), finite(quote.get("ask_price"))
    quote_time = int(quote.get("received_at_unix_ms") or 0)
    valid_quote = (opportunity.get("market_verified") is True and quote_time > 0
                   and 0 <= at - quote_time <= 2000 and bid is not None and ask is not None
                   and 0 < bid <= ask)
    model = opportunity.get("cost_model") or {}
    fee, slippage = finite(model.get("fee_rate")), finite(model.get("slippage_bps"))
    known_costs = valid_quote and fee is not None and slippage is not None and fee >= 0 and slippage >= 0
    components = {"fees_percent": 200 * fee if known_costs else None,
        "spread_percent": 100 * (ask - bid) / ((ask + bid) / 2) if known_costs else None,
        "base_slippage_percent": slippage / 50 if known_costs else None,
        "impact_percent": None}
    return {"version": VERSION, "strategy_epoch_id": epoch_id, "learning_context": context,
        "source_coverage": sources["coverage"], "excluded_counts": dict(rejected),
        "edge": {"status": "NO_VERIFIED_EDGE", "horizon_seconds": None,
            "sample_size": len(eligible), "expected_gross_return_percent": None,
            "expected_cost_percent": None, "uncertainty_reserve_percent": None,
            "expected_net_edge_percent": None, "cost_components": components,
            "known_cost_components_percent": sum(v for v in components.values() if v is not None) if known_costs else None,
            "cost_assumption": "stationary current BBO, round-trip taker fees and base slippage; quantity-dependent impact unavailable",
            "missing_support": ["prospective horizon return labels", "validated forecast", "out-of-sample evaluation", "quantity-dependent impact"]},
        "measurement_mode": "CAPTURED_DECISION_ASOF_RESEARCH", "execution_authority": False,
        "live_policy_changed": False}
