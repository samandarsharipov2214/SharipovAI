#!/usr/bin/env python3
"""Generate a canonical Phase 10 monthly performance report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from campaigns.phase10_scaling import ControlledScalingService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="UTC month in YYYY-MM format")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    service = ControlledScalingService()
    prefix = args.month + "-"
    snapshots = [row for row in service.list_snapshots(5000) if str(row.get("metrics", {}).get("date", "")).startswith(prefix) or str(row.get("metrics", {}).get("month", "")) == args.month]
    report = service.monthly_report(snapshots, month=args.month)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if report.get("drawdown_alert") else 0


if __name__ == "__main__":
    raise SystemExit(main())
