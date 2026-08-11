"""Bounded retention utility for high-volume canonical database data.

Dry-run is the default. Deletion requires --apply and an explicit confirmation.
Immutable evidence namespaces are never eligible. The utility currently targets
only project_events because it has stable canonical schema and timestamp fields.
Other tables must be added deliberately after schema-specific review.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass

from storage.project_database import ProjectDatabase

APPLY_CONFIRMATION = "I_APPROVE_BOUNDED_PROJECT_EVENT_RETENTION"
# Retention is deliberately conservative. These prefixes cover canonical audit,
# decision, execution, risk, portfolio, paper and learning provenance. Adding a
# new immutable namespace should extend this deny-list before retention is ever
# applied in production.
PROTECTED_NAMESPACE_PREFIXES = (
    "audit",
    "evidence",
    "execution",
    "decision",
    "promotion",
    "settlement",
    "learning",
    "self_learning",
    "security",
    "deployment",
    "risk",
    "portfolio",
    "trading",
    "council",
    "paper",
    "authorization",
    "agent",
)
DEFAULT_RETAIN_DAYS = 30
DEFAULT_BATCH_SIZE = 5000


@dataclass(frozen=True)
class RetentionResult:
    mode: str
    cutoff_ms: int
    retain_days: int
    batch_size: int
    eligible_rows: int
    deleted_rows: int


def _protected(namespace: str) -> bool:
    lowered = namespace.strip().lower()
    return any(
        lowered == prefix
        or lowered.startswith(prefix + "_")
        or lowered.startswith(prefix + ".")
        for prefix in PROTECTED_NAMESPACE_PREFIXES
    )


def _eligible_namespaces(db: ProjectDatabase, cutoff_ms: int) -> list[str]:
    with db.connect() as connection:
        rows = db._fetchall(
            connection,
            "SELECT DISTINCT namespace FROM project_events WHERE created_at_ms < ? ORDER BY namespace",
            (cutoff_ms,),
        )
    return [str(row["namespace"]) for row in rows if not _protected(str(row["namespace"]))]


def _count(db: ProjectDatabase, namespaces: list[str], cutoff_ms: int) -> int:
    if not namespaces:
        return 0
    placeholders = ",".join("?" for _ in namespaces)
    with db.connect() as connection:
        row = db._fetchone(
            connection,
            f"SELECT COUNT(*) AS count FROM project_events WHERE created_at_ms < ? AND namespace IN ({placeholders})",
            (cutoff_ms, *namespaces),
        )
    return int((row or {}).get("count") or 0)


def run_retention(*, db: ProjectDatabase, retain_days: int, batch_size: int, apply: bool) -> RetentionResult:
    if retain_days < 7:
        raise ValueError("retain_days must be at least 7")
    if batch_size < 1 or batch_size > 50000:
        raise ValueError("batch_size must be within 1..50000")
    db.initialize()
    cutoff_ms = int(time.time() * 1000) - retain_days * 86_400_000
    namespaces = _eligible_namespaces(db, cutoff_ms)
    eligible = _count(db, namespaces, cutoff_ms)
    if not apply or not namespaces or eligible == 0:
        return RetentionResult("dry-run", cutoff_ms, retain_days, batch_size, eligible, 0)

    deleted = 0
    placeholders = ",".join("?" for _ in namespaces)
    while deleted < eligible:
        with db.connect() as connection:
            try:
                db._begin(connection, immediate=True)
                rows = db._fetchall(
                    connection,
                    f"SELECT event_id FROM project_events WHERE created_at_ms < ? AND namespace IN ({placeholders}) ORDER BY created_at_ms ASC LIMIT ?",
                    (cutoff_ms, *namespaces, batch_size),
                )
                ids = [str(row["event_id"]) for row in rows]
                if not ids:
                    connection.rollback()
                    break
                id_placeholders = ",".join("?" for _ in ids)
                cursor = db._execute(
                    connection,
                    f"DELETE FROM project_events WHERE event_id IN ({id_placeholders})",
                    tuple(ids),
                )
                connection.commit()
                affected = int(getattr(cursor, "rowcount", 0) or len(ids))
                deleted += affected if affected > 0 else len(ids)
            except Exception:
                connection.rollback()
                raise
    return RetentionResult("apply", cutoff_ms, retain_days, batch_size, eligible, deleted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retain-days",
        type=int,
        default=int(os.getenv("SHARIPOVAI_PROJECT_EVENT_RETAIN_DAYS", DEFAULT_RETAIN_DAYS)),
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        parser.error(f"--apply requires --confirm {APPLY_CONFIRMATION}")
    result = run_retention(
        db=ProjectDatabase(),
        retain_days=args.retain_days,
        batch_size=args.batch_size,
        apply=args.apply,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
