"""Evaluate a sealed, bounded canonical opportunity export; never promote it."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from autonomous_trading.forecast_contract import digest
from learning_engine.prospective_validation import claim_holdout, evaluate
from storage import ProjectDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest["coverage"] != "COMPLETE_CUTOFF" or args.source.stat().st_size > 512 * 1024**2:
        raise ValueError("bounded complete source required")
    seal = args.output.with_suffix(".holdout-seal.json")
    # This local receipt supplements the canonical range claim below.
    with seal.open("x") as out:
        json.dump({"source_sha256": manifest["sha256"], "cutoff_ms": manifest["cutoff_ms"],
            "specification": "quote-ridge-300s-v1:fixed-ridge-0.001:60-20-20-global-purge",
            "execution_authority": False}, out, indent=2)
    rows, h = [], hashlib.sha256()
    scalar_keys = ("opportunity_id", "decision_time_ms", "recorded_at_ms", "physical_stored_at_ms",
                   "capture_digest", "market_verified")
    quote_keys = ("bid_price", "ask_price", "received_at_unix_ms", "feature_received_at_ms", "change_24h_percent", "volume_24h")
    costs = {}
    with args.source.open("rb") as source:
        for line in source:
            h.update(line)
            raw = json.loads(line)
            row = {k: raw.get(k) for k in scalar_keys}
            row.update(scope=sys.intern(raw["scope"]), symbol=sys.intern(raw["symbol"]))
            q = raw.get("quote")
            row["quote"] = {k: q.get(k) for k in quote_keys} if q else None
            cost = raw.get("cost_model") or {}
            key = tuple(sorted(cost.items()))
            row["cost_model"] = costs.setdefault(key, cost)
            rows.append(row)
            if len(rows) > 1_000_000:
                raise ValueError("source row bound exceeded")
    if h.hexdigest() != manifest["sha256"] or len(rows) != manifest["source_rows"]:
        raise ValueError("source manifest integrity failure")
    cutoff = manifest["cutoff_ms"]
    if not rows or any(r["scope"] != manifest["scope"] or not
                      0 < r["decision_time_ms"] <= r["recorded_at_ms"] <= cutoff for r in rows):
        raise ValueError("source scope or cutoff mismatch")
    first = min(r["decision_time_ms"] for r in rows)
    claim = claim_holdout(ProjectDatabase(), scope=manifest["scope"],
        start_ms=first + int((cutoff - first) * .8), end_ms=cutoff, source_sha256=manifest["sha256"])
    artifact = evaluate(rows, cutoff_ms=manifest["cutoff_ms"], source_coverage=manifest["coverage"], holdout_sealed=True)
    artifact["export_provenance"] = {"sha256": manifest["sha256"], "source_rows": len(rows),
        "scope": manifest["scope"], "holdout_seal_sha256": digest(json.loads(seal.read_text())),
        "canonical_holdout_claim": claim}
    with args.output.open("x") as out:
        out.write(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"model_sha256": digest(artifact), "status": artifact["validation"]["status"],
        "failures": artifact["validation"]["promotion_failures"],
        "train": artifact["support_count"], "test": artifact["validation"]["test_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
