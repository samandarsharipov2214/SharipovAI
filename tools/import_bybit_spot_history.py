#!/usr/bin/env python3
"""Build a canonical Bybit Spot historical dataset for Alpha validation.

Example:
    python tools/import_bybit_spot_history.py \
        --output-dir /var/lib/sharipovai/research/btc-eth-sol-15m-v1 \
        --dataset-id btc-eth-sol-15m \
        --dataset-version v1 \
        --start 2024-01-01T00:00:00Z \
        --end 2026-07-31T23:45:00Z

The command is public-data-only. It never authenticates to Bybit and never
submits an order. Raw Bybit kline timestamps are bar-open times; the importer
stores canonical timestamps at bar close and excludes any still-open candle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

from historical_data import BybitSpotKlineImporter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument(
        "--symbols",
        default="BTCUSDT,ETHUSDT,SOLUSDT",
        help="Comma-separated Spot symbols (default: BTCUSDT,ETHUSDT,SOLUSDT)",
    )
    parser.add_argument("--interval", default="15", help="Fixed Bybit minute interval (default: 15)")
    parser.add_argument("--start", required=True, help="First Bybit bar-open timestamp (ISO-8601 or ms)")
    parser.add_argument("--end", required=True, help="Last Bybit bar-open timestamp (ISO-8601 or ms)")
    parser.add_argument(
        "--commit-sha",
        default="",
        help="Importer/build git SHA; defaults to current repository HEAD",
    )
    parser.add_argument("--default-spread-bps", type=float, default=2.0)
    args = parser.parse_args()

    commit_sha = args.commit_sha.strip() or _current_git_sha()
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    importer = BybitSpotKlineImporter()
    result = importer.build_dataset(
        output_dir=Path(args.output_dir),
        dataset_id=args.dataset_id,
        dataset_version=args.dataset_version,
        symbols=symbols,
        interval=args.interval,
        start_bar_open_ms=_timestamp_ms(args.start),
        end_bar_open_ms=_timestamp_ms(args.end),
        commit_sha=commit_sha,
        default_spread_bps=args.default_spread_bps,
    )
    manifest_sha256 = _file_sha256(result.manifest_path)
    payload = {
        "status": "ok",
        "dataset_id": result.manifest.dataset_id,
        "dataset_version": result.manifest.dataset_version,
        "manifest_path": str(result.manifest_path),
        "manifest_sha256": manifest_sha256,
        "parquet_path": str(result.parquet_path),
        "row_count": result.manifest.row_count,
        "symbols": list(result.manifest.symbols),
        "interval_ms": result.manifest.interval_ms,
        "timestamp_semantics": result.manifest.timestamp_semantics,
        "sha256": dict(result.manifest.sha256),
        "missing_interval_count": result.validation.missing_interval_count,
        "final_oos_eligible": result.validation.final_oos_eligible,
        "oos_blockers": list(result.validation.oos_blockers),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if result.validation.final_oos_eligible else 2


def _timestamp_ms(value: str) -> int:
    clean = str(value).strip()
    if clean.isdigit():
        parsed = int(clean)
        if parsed <= 0:
            raise ValueError("timestamp must be positive")
        return parsed
    try:
        moment = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("ISO-8601 timestamps must include a timezone")
    parsed = int(moment.timestamp() * 1000)
    if parsed <= 0:
        raise ValueError("timestamp must be positive")
    return parsed


def _current_git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
