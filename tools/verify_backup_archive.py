"""Safely extract a downloaded SharipovAI backup archive and verify its manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.backup_integrity import BackupIntegrityError, extract_verified_archive


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = extract_verified_archive(args.archive, args.destination)
    except (OSError, ValueError, BackupIntegrityError) as exc:
        print(f"backup verification failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "status": "ok",
                "created_at": manifest.get("created_at"),
                "file_count": manifest.get("file_count"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
