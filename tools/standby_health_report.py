"""Unified readiness report for the passive SharipovAI PC standby node."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _age_seconds(value: object) -> float | None:
    try:
        created = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return max(0.0, time.time() - created.timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def build_report(project_root: Path, maximum_age_seconds: int) -> dict[str, Any]:
    root = project_root.resolve()
    runtime = root / "runtime"
    snapshot = runtime / "remote_backups" / "current"
    manifest_path = snapshot / "manifest.json"
    sync_status_path = runtime / "vps_backup_sync_status.json"
    active_node_path = runtime / "active_node.json"

    manifest = _read_json(manifest_path)
    sync_status = _read_json(sync_status_path)
    active_node = _read_json(active_node_path)
    reasons: list[str] = []

    if manifest is None:
        reasons.append("verified backup manifest is missing or invalid")
        backup_age = None
        file_count = 0
    else:
        backup_age = _age_seconds(manifest.get("created_at"))
        file_count = int(manifest.get("file_count") or len(manifest.get("files") or []))
        if manifest.get("source") != "vps":
            reasons.append("backup source is not VPS")
        if backup_age is None:
            reasons.append("backup timestamp is invalid")
        elif backup_age > maximum_age_seconds:
            reasons.append("verified VPS backup is stale")
        if file_count < 1:
            reasons.append("verified backup contains no files")

    sync_ok = bool(sync_status and sync_status.get("status") == "ok")
    if not sync_ok:
        reasons.append("last VPS backup synchronization did not complete successfully")

    active = str((active_node or {}).get("active_node") or "standby").lower()
    if active not in {"standby", "pc"}:
        reasons.append(f"unknown active node marker: {active}")

    if manifest is None or not sync_ok or file_count < 1:
        status = "BLOCKED"
    elif backup_age is None or backup_age > maximum_age_seconds:
        status = "STALE"
    else:
        status = "READY"

    return {
        "schema": 1,
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "project_root": str(root),
        "active_node": active,
        "maximum_backup_age_seconds": maximum_age_seconds,
        "backup": {
            "manifest_path": str(manifest_path),
            "created_at": manifest.get("created_at") if manifest else None,
            "age_seconds": round(backup_age, 3) if backup_age is not None else None,
            "file_count": file_count,
            "source": manifest.get("source") if manifest else None,
        },
        "synchronization": sync_status or {"status": "missing"},
        "reasons": reasons,
        "failover_allowed": status == "READY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Report SharipovAI standby readiness")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--maximum-age-seconds",
        type=int,
        default=int(os.getenv("SHARIPOVAI_STANDBY_MAX_BACKUP_AGE_SECONDS", "7200")),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.maximum_age_seconds < 60:
        print("maximum backup age must be at least 60 seconds", file=sys.stderr)
        return 2
    report = build_report(args.project_root, args.maximum_age_seconds)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    output = args.output or args.project_root / "runtime" / "standby_health.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    os.replace(temporary, output)
    print(rendered)
    return 0 if report["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
