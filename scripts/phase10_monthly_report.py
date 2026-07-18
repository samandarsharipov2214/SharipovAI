#!/usr/bin/env python3
"""Generate an immutable UTC monthly performance report."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from campaigns.phase10_scaling import ControlledScalingService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="UTC month in YYYY-MM format")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    service = ControlledScalingService()
    report = service.monthly_report(service.list_snapshots(10000), month=args.month)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report.get("drawdown_alert"):
        return 2
    if int(report.get("matched_fill_count") or 0) == 0:
        return 3
    return 0


def _atomic_json_write(output: Path, payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, output)
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
