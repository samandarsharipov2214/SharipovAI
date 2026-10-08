"""Read-only end-to-end PAPER decision diagnosis for Astra.

It reports the most recent per-symbol canonical trace.  It never ticks a
strategy, changes a limit, consumes authorization, or creates a trade.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Mapping
from typing import Any

# The production container binds the reviewed checkout at /workspace but runs
# the immutable deployed build from /app.  Prefer that build so a diagnostic
# cannot silently inspect a different source tree or fail on bind permissions.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from storage import ProjectDatabase, list_json_items


def _reason_code(trace: Mapping[str, Any]) -> str:
    reason = str(trace.get("reason") or "").lower()
    if "no market" in reason or "market_data" in reason:
        return "NO_MARKET_DATA"
    if "stale" in reason or "age" in reason:
        return "STALE_MARKET_DATA"
    if "time-aligned" in reason or "lineage" in reason:
        return "QUOTE_LINEAGE_REJECTED"
    if "liquidity" in reason:
        return "RISK_INSUFFICIENT_LIQUIDITY"
    if "short position" in reason:
        return "SPOT_SELL_WITHOUT_POSITION"
    if "threshold" in reason or "no signal" in reason:
        return "NO_ENTRY_SIGNAL"
    if "consensus" in reason or "decision_quality" in reason:
        return "CONSENSUS_OR_DECISION_GATE"
    if "risk" in reason:
        return "RISK_GATE"
    if "cash" in reason or "balance" in reason:
        return "INSUFFICIENT_PAPER_BALANCE"
    if "execution" in reason:
        return "PAPER_EXECUTION_GATE"
    return "WAIT_OR_BLOCK_UNCLASSIFIED"


def collect(database: ProjectDatabase | None = None) -> dict[str, Any]:
    database = database or ProjectDatabase()
    database.initialize()
    traces = list_json_items(database, "council_decision_trace", limit=128, newest_first=False)
    latest: dict[str, dict[str, Any]] = {}
    for row in traces:
        value = row.get("value")
        if not isinstance(value, Mapping):
            continue
        symbol = str(value.get("symbol") or row.get("item_key") or "")
        if not symbol:
            continue
        if int(value.get("updated_at_ms") or 0) >= int(latest.get(symbol, {}).get("updated_at_ms") or 0):
            latest[symbol] = dict(value)
    results = []
    for symbol, trace in sorted(latest.items()):
        decision_id = str(trace.get("decision_id") or "")
        decision_row = database.get_json("paper_v2_decisions", decision_id) if decision_id else None
        decision = decision_row.get("value") if isinstance(decision_row, Mapping) else {}
        decision = decision if isinstance(decision, Mapping) else {}
        controller = decision.get("controller")
        controller = controller if isinstance(controller, Mapping) else {}
        results.append({
            "symbol": symbol,
            "timestamp_ms": int(trace.get("updated_at_ms") or 0),
            "decision_id": decision_id,
            "strategy": str(trace.get("paper_strategy_version") or "canonical_council_paper"),
            "source": "council_decision_trace",
            "status": str(trace.get("status") or "UNKNOWN"),
            "reason_code": _reason_code(trace),
            "reason": str(trace.get("reason") or "")[:800],
            "market_verified": trace.get("market_verified"),
            "quote_age_ms": trace.get("quote_age_ms"),
            "authorized": trace.get("authorized"),
            "candidate_validation_valid": trace.get("candidate_validation_valid"),
            "candidate_side": decision.get("candidate_side"),
            "controller_final_intent": controller.get("final_intent"),
            "risk_blocks": list(trace.get("risk_blocks") or []),
            "constraints": {
                "required_consensus_source_count": trace.get("required_consensus_source_count"),
                "consensus_source_count": trace.get("consensus_source_count"),
                "decision_quality_confidence": trace.get("decision_quality_confidence"),
                "decision_quality_agreement": trace.get("decision_quality_agreement"),
                "execution_authority": trace.get("execution_authority"),
            },
        })
    return {"status": "VERIFIED", "generated_at_ms": int(time.time() * 1000),
            "read_only": True, "symbols": results,
            "summary": {"symbols_observed": len(results),
                        "natural_entries": sum(1 for item in results if item["status"] not in {"WAIT", "BLOCK"})}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="optional output file; stdout is default")
    args = parser.parse_args()
    result = collect()
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
