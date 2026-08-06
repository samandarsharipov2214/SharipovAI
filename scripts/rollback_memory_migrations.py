#!/usr/bin/env python3
"""Fail-closed rollback for Memory Layer tables only."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from memory_engine import MemoryMigrationManager
from storage import ProjectDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--backup-path", default="deploy/vps/backups/latest.tar.gz")
    parser.add_argument("--confirm-drop-memory", action="store_true")
    args = parser.parse_args()

    if os.getenv("MEMORY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}:
        raise SystemExit("Refusing rollback while MEMORY_ENABLED is true")
    backup = Path(args.backup_path)
    if not backup.is_file() or backup.stat().st_size <= 0:
        raise SystemExit(f"Refusing rollback without a visible non-empty backup: {backup}")
    database = ProjectDatabase(dsn=args.database_url or None)
    manager = MemoryMigrationManager(database)
    health = manager.health()
    if not args.confirm_drop_memory:
        print({"status": "dry_run", "memory_health": health, "backup": str(backup)})
        print("Re-run with --confirm-drop-memory after reviewing the verified backup.")
        return 0
    manager.rollback(confirmed=True)
    print({"status": "rolled_back", "backup": str(backup), "memory_tables_removed": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
