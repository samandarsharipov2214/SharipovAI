"""Explicit, archive-first retention of proven disposable operational events."""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from storage import ProjectDatabase
from storage.lifecycle import DEFAULT_RETAIN_DAYS, retain

APPLY_CONFIRMATION = 'I_APPROVE_BOUNDED_PROJECT_EVENT_RETENTION'
DEFAULT_BATCH_SIZE = 100


@dataclass(frozen=True)
class RetentionResult:
    mode: str
    cutoff_ms: int
    retain_days: int
    batch_size: int
    eligible_rows: int
    deleted_rows: int


def run_retention(*, db: ProjectDatabase, retain_days: int, batch_size: int, apply: bool) -> RetentionResult:
    root = (Path(db.dsn.removeprefix('sqlite:///')).parent if db.backend == 'sqlite'
            else Path(os.getenv('SHARIPOVAI_DATA_DIR', 'data')))
    result = retain(db, root / 'storage-archives', retain_days=retain_days, batch_size=batch_size, apply=apply)
    return RetentionResult('apply' if apply else 'dry-run', result['cutoff_ms'], retain_days,
                           batch_size, result['selected'], result['deleted'])


def _valid_backup_evidence(path: Path | None) -> bool:
    """Compatibility helper: require actual archive hash and a successful restore."""
    from tools.backup_integrity import sha256
    from datetime import datetime, timezone
    try:
        value = json.loads(path.read_text()) if path else {}
        archive = Path(value['archive'])
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(value['source_created_at'])).total_seconds()
        return (-300 <= age <= 86400 and value['status'] == 'ok' and bool(value['sqlite_checks'])
                and all(check['status'] == 'ok' for check in value['sqlite_checks'])
                and sha256(archive) == value['archive_sha256'])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retain-days', type=int, default=int(os.getenv('SHARIPOVAI_PROJECT_EVENT_RETAIN_DAYS', DEFAULT_RETAIN_DAYS)))
    parser.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm', default='')
    args = parser.parse_args()
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        parser.error(f'--apply requires --confirm {APPLY_CONFIRMATION}')
    # Every cohort is archived, fsynced and readback verified before any DELETE.
    # A nonempty text file is no longer accepted as recovery evidence.
    result = run_retention(db=ProjectDatabase(), retain_days=args.retain_days,
                           batch_size=args.batch_size, apply=args.apply)
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
