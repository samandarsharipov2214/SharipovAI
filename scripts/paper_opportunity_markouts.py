"""Create offline cost-aware diagnostics from an exported opportunity JSON list.

Example: python -m scripts.paper_opportunity_markouts --source opportunities.json
         --cutoff-ms 1789258307343 --output markouts.json
No runtime database, credentials, network requests or execution are used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from learning_engine.opportunity_markouts import fixed_horizon_markouts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--cutoff-ms", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--anchor-population", choices=("proposals", "all_opportunities"),
                        default="proposals", help="Include WAIT/no-proposal observations explicitly")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve prior evidence and choose a new path")
    rows = json.loads(args.source.read_text())
    if not isinstance(rows, list):
        parser.error("source must be an exported opportunity JSON list")
    report = fixed_horizon_markouts(rows, cutoff_ms=args.cutoff_ms, anchor_population=args.anchor_population)
    with args.output.open("x") as output:
        output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    args.output.chmod(0o600)
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))


if __name__ == "__main__":
    main()
