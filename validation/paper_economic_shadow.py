"""Deterministic as-of evidence validation, not a strategy profitability replay.

Input is an exported read-only canonical source snapshot plus captured
opportunities. No database, exchange, execution or configuration writes.
Run: python -m validation.paper_economic_shadow SOURCE_JSON OUTPUT_JSON
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from learning_engine.paper_economic_shadow import assess_opportunity, digest


def validate(document: dict) -> dict:
    sources = document["sources"]
    before = digest(sources)
    opportunities = sorted(document["opportunities"], key=lambda item: item["decision_time_ms"])
    results = [assess_opportunity(opportunity, sources) for opportunity in opportunities]
    checks = {
        "immutable_sources_preserved": digest(sources) == before,
        "all_shadow_only": all(r["execution_authority"] is False and r["live_policy_changed"] is False for r in results),
        "no_fabricated_edge": all(r["edge"]["expected_net_edge_percent"] is None for r in results),
        "no_late_failure_memory": all(not r["learning_context"]["recent_failed_hypothesis"] or
            r["learning_context"]["recent_failed_hypothesis"]["available_at_ms"] < op["decision_time_ms"]
            for op, r in zip(opportunities, results)),
        "no_accounting_mismatches": all(r["excluded_counts"].get("accounting_mismatch", 0) == 0 for r in results),
        "complete_source_snapshot": sources["coverage"] == "COMPLETE_SNAPSHOT",
    }
    return {"classification": "MEASUREMENT_FIX", "validation": "PASS" if all(checks.values()) else "FAIL",
        "source_digest": before, "checks": checks, "opportunities": len(opportunities),
        "results": results, "profitability_evidence": "INSUFFICIENT_EVIDENCE",
        "strategy_counterfactual": "NOT_RUN; trading policy and risk budget unchanged"}


if __name__ == "__main__":
    result = validate(json.loads(Path(sys.argv[1]).read_text()))
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2))
    raise SystemExit(0 if result["validation"] == "PASS" else 1)
