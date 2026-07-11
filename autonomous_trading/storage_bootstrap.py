"""Local storage layout and startup readiness for SharipovAI."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from persistence_paths import durable_data_path

DIRECTORIES = (
    "Database", "Memory", "News", "Trading", "Market", "Logs",
    "Reports", "Backups", "Cache", "Temp", "AI", "Config",
)


def storage_root() -> Path:
    explicit = os.getenv("SHARIPOVAI_HOME")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        return Path(r"D:\SharipovAI")
    return durable_data_path("SHARIPOVAI_HOME_FILE", "data/.keep").parent


def readiness_file() -> Path:
    return storage_root() / "Trading" / "startup_readiness.json"


def bootstrap_storage(recovery: dict[str, Any]) -> dict[str, Any]:
    root = storage_root()
    created: list[str] = []
    errors: list[str] = []
    try:
        root.mkdir(parents=True, exist_ok=True)
        for name in DIRECTORIES:
            path = root / name
            path.mkdir(parents=True, exist_ok=True)
            created.append(str(path))
    except OSError as exc:
        errors.append(f"{type(exc).__name__}: {exc}")

    recovery_failed = list(recovery.get("failed", [])) if isinstance(recovery, dict) else [{"error": "invalid recovery result"}]
    trading_ready = not errors and not recovery_failed
    payload = {
        "status": "ready" if trading_ready else "blocked",
        "trading_ready": trading_ready,
        "checked_at": datetime.now(UTC).isoformat(),
        "root": str(root),
        "created_directories": created,
        "storage_errors": errors,
        "recovery_failed": recovery_failed,
    }
    target = readiness_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(target) + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)
    return payload


def trading_storage_ready() -> tuple[bool, str]:
    path = readiness_file()
    if not path.exists():
        return False, "startup readiness file is missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"startup readiness file is invalid: {type(exc).__name__}"
    if payload.get("trading_ready") is not True:
        return False, "startup recovery/storage check did not pass"
    return True, "ok"
