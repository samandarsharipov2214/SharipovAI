#!/usr/bin/env python3
"""Safely backfill legacy SaaS web chat history into ProjectDatabase.

Default mode is read-only and reports how many legacy rows are present. Pass
``--apply`` explicitly to perform the idempotent canonical append migration.
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import func, select

from dashboard.db_saas import SessionLocal
from dashboard.legacy_chat_history_migration import backfill_legacy_web_chat_history
from dashboard.models_saas import ChatMessageLog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="append legacy rows to canonical ProjectDatabase history",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="streaming batch size, clamped to 1..5000",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    db = SessionLocal()
    try:
        legacy_rows = int(db.scalar(select(func.count(ChatMessageLog.id))) or 0)
        if not args.apply:
            print(
                json.dumps(
                    {
                        "status": "dry_run",
                        "legacy_rows": legacy_rows,
                        "mutation_performed": False,
                    },
                    sort_keys=True,
                )
            )
            return 0

        result = backfill_legacy_web_chat_history(
            db,
            batch_size=args.batch_size,
        )
        print(
            json.dumps(
                {
                    "status": "applied",
                    "legacy_rows": legacy_rows,
                    "mutation_performed": True,
                    **result,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
