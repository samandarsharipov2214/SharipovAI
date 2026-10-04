"""Learning-owned metadata gate. Never fit, predict, calculate returns or open OOS.

The incremental state is an operational projection of canonical opportunity
events. It contains counts/timestamps only, not prices, labels or model scores.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

from autonomous_trading.forecast_contract import digest, quote_features, timestamp

DAY = 86_400_000
INTERVAL_MS = 6 * 60 * 60 * 1000
HORIZON_MS = 300_000
TOLERANCE_MS = 10_000
NAMESPACE = "paper_forecast_readiness"
ALGORITHM_VERSION = "paper-readiness-metadata-v2"


def algorithm_identity() -> dict:
    root = Path(__file__).resolve().parent.parent
    paths = ("learning_engine/forecast_readiness.py", "scripts/paper_forecast_readiness.py",
             "autonomous_trading/forecast_contract.py")
    return {"version": ALGORITHM_VERSION, "source_sha256": {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}}


def new_state(plan: dict, *, cursor: int) -> dict:
    return {"plan_sha256": digest(plan), "algorithm": algorithm_identity(),
            "cursor": cursor, "anchor_rowid": None,
            "anchor_event_id": None, "last_checked_at_ms": 0, "rows": 0,
            "verified_quotes": 0, "feature_timestamp_present": 0,
            "first_source_ms": None, "last_source_ms": None, "symbols": {},
            "partitions": {key: {"anchors": 0, "matured": 0, "valid": 0,
                                    "first_valid_ms": None, "last_valid_ms": None,
                                    "symbols": {}, "regimes": {}}
                           for key in ("train", "calibration", "test")},
            "rejections": {}, "fatal_errors": [], "trigger_status": "not_requested",
            "execution_authority": False}


def partition(plan: dict, at: int) -> str | None:
    if not plan["source_start_ms"] <= at < plan["holdout_end_ms"] - HORIZON_MS - TOLERANCE_MS:
        return None
    if at < plan["calibration_start_ms"]:
        return "train"
    return "calibration" if at < plan["holdout_start_ms"] else "test"


def _positive_time(value: Any) -> bool:
    try:
        timestamp(value)  # Canonical capture encodes integral milliseconds as floats too.
        return True
    except (ValueError, TypeError, OverflowError):
        return False


def _quote_valid(row: dict) -> bool:
    q = row.get("quote") or {}
    try:
        bid, ask, received = q["bid_price"], q["ask_price"], q["received_at_unix_ms"]
        return (row.get("market_verified") is True and _positive_time(received)
                and all(type(v) in (int, float) and math.isfinite(v) for v in (bid, ask))
                and 0 < bid <= ask and 0 <= row["decision_time_ms"] - received <= 2000)
    except (KeyError, TypeError):
        return False


def _quality(row: dict, stored: int) -> str | None:
    try:
        at, recorded = row["decision_time_ms"], row["recorded_at_ms"]
        if (not _positive_time(at) or not _positive_time(recorded)
                or not at <= recorded < at + HORIZON_MS or recorded != stored):
            return "physical_capture_provenance"
        capture = row.get("capture_digest")
        if not isinstance(capture, str) or len(capture) != 64 or any(c not in "0123456789abcdef" for c in capture):
            return "capture_digest_missing"
        if not _quote_valid(row):
            return "invalid_entry_quote"
        quote_features(row["quote"], as_of_ms=at, require_timestamps=True)
        cost = row["cost_model"]
        for key in ("fee_rate", "slippage_bps", "market_impact_bps", "max_participation_rate"):
            value = cost[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return "invalid_cost_provenance"
        if not cost["fee_rate"] < 1 or not 0 < cost["max_participation_rate"] <= 1:
            return "invalid_cost_provenance"
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        return "invalid_feature_provenance:" + type(error).__name__
    return None


def _finish(state: dict, pending: dict, reason: str | None) -> None:
    stats = state["partitions"][pending["partition"]]
    stats["matured"] += 1
    if reason is not None:
        state["rejections"][reason] = state["rejections"].get(reason, 0) + 1
    else:
        stats["valid"] += 1
        at = pending["at"]
        stats["first_valid_ms"] = at if stats["first_valid_ms"] is None else min(at, stats["first_valid_ms"])
        stats["last_valid_ms"] = at if stats["last_valid_ms"] is None else max(at, stats["last_valid_ms"])
        for field in ("symbol", "regime"):
            groups = stats[field + "s"]
            groups[pending[field]] = groups.get(pending[field], 0) + 1


def advance(state: dict, plan: dict, events: list[dict], *, now_ms: int) -> dict:
    """Reserve nonoverlapping anchors before quality checks; never inspect returns."""
    if state.get("algorithm") != plan.get("readiness_algorithm") or state.get("algorithm") != algorithm_identity():
        raise ValueError("readiness_algorithm_changed")
    state = copy.deepcopy(state)
    for event in events:
        row, rid = event["value"], event["rowid"]
        if rid <= state["cursor"]:
            raise ValueError("event cursor must advance")
        state.update(cursor=rid, anchor_rowid=rid, anchor_event_id=event["event_id"])
        if row.get("scope") != plan["scope"] or row.get("symbol") not in plan["symbols"]:
            state["fatal_errors"] = ["unexpected_source_identity"]
            continue
        at = row.get("decision_time_ms")
        if not _positive_time(at) or at > event["stored_at_ms"] or event["stored_at_ms"] > now_ms:
            state["fatal_errors"] = ["invalid_source_time"]
            continue
        symbol = state["symbols"].setdefault(row["symbol"], {"last_ms": 0, "next_anchor_ms": 0, "pending": None})
        if at < symbol["last_ms"]:
            state["fatal_errors"] = ["out_of_order_canonical_capture"]
            continue
        symbol["last_ms"] = at
        quality = _quality(row, event["stored_at_ms"])
        if plan["source_start_ms"] <= at <= plan["holdout_end_ms"]:
            state["rows"] += 1
            state["first_source_ms"] = at if state["first_source_ms"] is None else min(state["first_source_ms"], at)
            state["last_source_ms"] = at if state["last_source_ms"] is None else max(state["last_source_ms"], at)
            if _quote_valid(row):
                state["verified_quotes"] += 1
                state["feature_timestamp_present"] += int(_positive_time(row["quote"].get("feature_received_at_ms")))
        pending = symbol["pending"]
        if pending:
            target = pending["at"] + HORIZON_MS
            received = (row.get("quote") or {}).get("received_at_unix_ms", 0)
            if _quote_valid(row) and received >= target:
                reason = pending["reason"] or quality
                feature_time = row["quote"].get("feature_received_at_ms")
                if received > target + TOLERANCE_MS:
                    reason = "missing_future_quote"
                elif not _positive_time(feature_time) or not target <= feature_time <= target + TOLERANCE_MS:
                    reason = "label_feature_time_outside_horizon"
                boundary = {"train": plan["calibration_start_ms"], "calibration": plan["holdout_start_ms"],
                            "test": plan["holdout_end_ms"]}[pending["partition"]]
                if event["stored_at_ms"] >= boundary:
                    reason = "purged_boundary_label"
                _finish(state, pending, reason)
                symbol["pending"] = None
            elif at > target + TOLERANCE_MS + 2000:
                _finish(state, pending, pending["reason"] or "missing_future_quote")
                symbol["pending"] = None
        part = partition(plan, at)
        if part and at >= symbol["next_anchor_ms"]:
            if symbol["pending"] is not None:
                _finish(state, symbol["pending"], "missing_future_quote")
            state["partitions"][part]["anchors"] += 1
            symbol["next_anchor_ms"] = at + HORIZON_MS + TOLERANCE_MS + 1
            change = (row.get("quote") or {}).get("change_24h_percent")
            regime = ("up_24h" if change >= .8 else "down_24h" if change <= -.8 else "range_24h") if quality is None else "unavailable"
            symbol["pending"] = {"at": at, "partition": part, "reason": quality,
                                 "symbol": row["symbol"], "regime": regime}
    return state


def expected_anchors(plan: dict, part: str) -> int:
    """Clock-based denominator includes outages and rows never persisted.

    Exclude the final horizon at each boundary, where no label can be available
    without crossing the next partition. Count every frozen supported symbol.
    """
    boundaries = {"train": (plan["source_start_ms"], plan["calibration_start_ms"]),
                  "calibration": (plan["calibration_start_ms"], plan["holdout_start_ms"]),
                  "test": (plan["holdout_start_ms"], plan["holdout_end_ms"])}
    lo, hi = boundaries[part]
    duration = max(0, hi - lo - HORIZON_MS - TOLERANCE_MS)
    return math.ceil(duration / (HORIZON_MS + TOLERANCE_MS + 1)) * len(plan["symbols"])


def readiness(state: dict, plan: dict, *, now_ms: int, caught_up: bool, claims: dict) -> dict:
    reasons = list(state["fatal_errors"])
    if state.get("algorithm") != plan.get("readiness_algorithm") or state.get("algorithm") != algorithm_identity():
        reasons.append("readiness_algorithm_changed")
    if state["plan_sha256"] != digest(plan):
        reasons.append("frozen_plan_changed")
    if now_ms < plan["holdout_end_ms"]:
        reasons.append("future_source_window_incomplete")
    if not caught_up:
        reasons.append("source_cursor_not_caught_up")
    span = ((state["last_source_ms"] or 0) - (state["first_source_ms"] or 0)) / DAY
    if span < 28:
        reasons.append("source_span_below_28_days")
    completeness = state["feature_timestamp_present"] / state["verified_quotes"] if state["verified_quotes"] else 0
    if completeness < 1:
        reasons.append("independent_feature_timestamp_incomplete")
    coverage = {}
    for part, minimum in (("train", 500), ("calibration", 200), ("test", 200)):
        counts = state["partitions"][part]
        denominator = max(counts["anchors"], expected_anchors(plan, part))
        coverage[part] = {"expected_anchors": denominator,
                          "valid_fraction": counts["valid"] / denominator if denominator else 0}
        if counts["valid"] < minimum:
            reasons.append(part + "_support_insufficient")
        if coverage[part]["valid_fraction"] < .8:
            reasons.append(part + "_coverage_below_80_percent")
    test = state["partitions"]["test"]
    test_span = ((test["last_valid_ms"] or 0) - (test["first_valid_ms"] or 0)) / DAY
    if test_span < 7:
        reasons.append("test_span_below_7_days")
    if any(test["symbols"].get(symbol, 0) < 50 for symbol in plan["symbols"]):
        reasons.append("test_symbol_support_insufficient")
    if any(test["regimes"].get(regime, 0) < 50 for regime in ("up_24h", "down_24h", "range_24h")):
        reasons.append("test_regime_support_insufficient")
    for claim in claims.values():
        lo, hi = claim["final_oos_range"]
        if lo <= plan["holdout_end_ms"] and hi >= plan["holdout_start_ms"]:
            reasons.append("holdout_already_consumed")
    return {"ready": not reasons, "reasons": reasons, "source_span_days": span,
            "test_span_days": test_span, "feature_timestamp_completeness": completeness,
            "testable_matured_labels": sum(s["valid"] for s in state["partitions"].values()),
            "partitions": state["partitions"], "coverage": coverage, "rejections": state["rejections"],
            "holdout_identity": plan["holdout_identity"], "execution_authority": False,
            "holdout_opened": False, "model_promoted": False}
