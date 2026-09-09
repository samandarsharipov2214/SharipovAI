"""Replay a supplied real settlement export into a disposable Learning database.

This checks accounting and evidence semantics, not strategy profitability. It
has no network or source-database access. Run the same file against baseline and
candidate imports to compare labels, confidence units and information timing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from learning_engine import SelfLearningSupervisor
from meta_ai_persistence import EVENT_NAMESPACE
from storage import ProjectDatabase


def validate_export(source):
    before = json.dumps(source, sort_keys=True, allow_nan=False)
    captured = int(datetime.fromisoformat(source["captured_at"]).timestamp() * 1000)
    trades = source["trades"]
    if not trades or any(t.get("verified_market_data") is not True for t in trades):
        raise ValueError("verified immutable financial trades are required")
    rows = sorted(source["records"], key=lambda r: (r["settlement_recorded_at_ms"], r["decision_id"]))
    closes = {t["decision_id"]: t for t in trades if t["side"] == "SELL"}
    if source.get("missing") or set(closes) != {r["decision_id"] for r in rows} or len(rows) != len(closes):
        raise ValueError("every close must have exactly one settlement and assessment")
    counts = Counter()
    with tempfile.TemporaryDirectory(prefix="learning-validation-") as temporary:
        database = ProjectDatabase(f"sqlite:///{temporary}/projection.db")
        supervisor = SelfLearningSupervisor(database)
        for row in rows:
            decision, event, settlement = row["decision_id"], row["assessment_event"], row["settlement"]
            available = row["settlement_recorded_at_ms"]
            close = closes[decision]
            if not (0 < event["created_at_ms"] <= close["created_at_ms"] <= available <= captured):
                raise ValueError("source chronology is inconsistent")
            if not math.isclose(settlement["net_pnl"], close["net_pnl"], abs_tol=1e-9):
                raise ValueError("settlement must reconcile with immutable close")
            database.append_event(EVENT_NAMESPACE, "decision_assessment", decision, event["payload"],
                                  created_at_ms=event["created_at_ms"])
            evidence = supervisor._evidence_from_settlement(decision, settlement, available)
            result = supervisor.attribution.record(evidence)
            counts["fabricated_direction_labels"] += settlement.get("realized_action") is None and result.get("realized_action") is not None
            counts["outcomes_timestamped_before_close"] += result["occurred_at_ms"] < close["created_at_ms"]
            counts["missing_availability_timestamp"] += result.get("evidence_available_at_ms") is None
            expected = {o["agent_id"]: o["confidence"] * 100 for o in event["payload"]["opinions"]}
            for attribution in result["attributions"]:
                counts["confidence_unit_mismatches"] += not math.isclose(attribution["confidence"], expected[attribution["agent_id"]], abs_tol=1e-9)
            assert supervisor.attribution.record(evidence)["idempotent"]
        summary = supervisor.attribution.summary()
    net = sum(t["net_pnl"] for t in closes.values())
    if not math.isclose(summary["net_pnl"], net, abs_tol=1e-9):
        raise ValueError("Learning projection must preserve all closed net losses and profits")
    assert before == json.dumps(source, sort_keys=True, allow_nan=False)
    return {
        "validation_type": "chronological_learning_projection",
        "source_sha256": hashlib.sha256(before.encode()).hexdigest(),
        "source_captured_at": source["captured_at"],
        "source_unchanged": True,
        "strategy_policy_changed": False,
        "execution_authority": False,
        "profitability_evidence": "INSUFFICIENT_EVIDENCE",
        "trades": len(trades), "closed_trades": len(closes),
        "symbols": sorted({t["symbol"] for t in trades}),
        "fees": sum(t["fee"] for t in trades),
        "turnover": sum(t.get("notional", t["price"] * t["quantity"]) for t in trades),
        "net_closed_pnl": net, "net_expectancy": net / len(closes),
        "evidence_violations": dict(counts), "learning_summary": summary,
        "limitations": ["No directional ground truth is inferred from a profit or loss.",
                        "No entry/exit policy, cash path or counterfactual strategy is simulated."],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = validate_export(json.loads(args.source.read_text()))
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
