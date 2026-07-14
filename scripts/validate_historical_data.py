"""Validate a historical-data manifest and its Parquet files."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from historical_data import DataManifest, validate_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate SharipovAI historical Parquet data"
    )
    parser.add_argument("manifest")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).resolve()
    manifest = DataManifest.load(manifest_path)
    report = validate_dataset(
        manifest,
        root=Path(args.root).resolve() if args.root else manifest_path.parent,
    )
    payload = asdict(report)
    payload["valid"] = report.valid
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
