#!/usr/bin/env python3
"""Run a pytest selection under coverage after native DuckDB preload.

The self-hosted runner can import DuckDB normally, but starting pytest-cov before
DuckDB causes the native ``_duckdb`` extension to be observed as a plain module
instead of its package-compatible form.  Importing the verified wheel before the
coverage tracer starts removes that environment contamination without excluding
historical-data tests or lowering the coverage threshold.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--data-file", type=Path, required=True)
    parser.add_argument("--fail-under", type=float, default=65.0)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser


def main() -> int:
    args = _parser().parse_args()
    pytest_args = list(args.pytest_args)
    if pytest_args and pytest_args[0] == "--":
        pytest_args.pop(0)
    if not pytest_args:
        raise SystemExit("pytest arguments are required after --")

    # Native extension must be fully initialized before coverage starts.
    import duckdb

    if duckdb.__version__ != "1.5.4":
        raise RuntimeError(f"unexpected DuckDB version: {duckdb.__version__}")

    import coverage
    import pytest

    args.xml.parent.mkdir(parents=True, exist_ok=True)
    args.data_file.parent.mkdir(parents=True, exist_ok=True)
    cov = coverage.Coverage(
        branch=True,
        source=args.source or None,
        data_file=str(args.data_file),
    )
    cov.erase()
    cov.start()
    try:
        pytest_status = int(pytest.main(pytest_args))
    finally:
        cov.stop()
        cov.save()

    measured = float(cov.report(show_missing=True))
    cov.xml_report(outfile=str(args.xml))
    if pytest_status != 0:
        return pytest_status
    if measured + 1e-9 < float(args.fail_under):
        print(
            f"coverage failure: {measured:.2f}% is below {args.fail_under:.2f}%",
            file=sys.stderr,
        )
        return 2
    print(f"critical coverage: {measured:.2f}% (minimum {args.fail_under:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
