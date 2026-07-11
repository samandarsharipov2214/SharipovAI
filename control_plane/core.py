"""Unified status, AI registry and safe local command queue for SharipovAI."""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_COMMANDS = {
    "restart_web",
    "restart_backup",
    "restart_all",
    "run_health_check",
    "apply_verified_update",
}


def component_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "general_ai",
            "name": "General AI",
            "role": "Central planning, routing and synthesis",
            "category": "core",
            "enabled": True,
            "overlaps": [],
        },
        {
            "id": "news_network",
            "name": "News Agent Network",
            "role": "Collection, verification and ranking of news",
            "category": "intelligence",
            "enabled": True,
            "overlaps": ["social_news"],
        },
        {
            "id": "market_data",
            "name": "Market Data",
            "role": "Verified quotes and market stream health",
            "category": "market",
            "enabled": True,
            "overlaps": [],
        },
        {
            "id": "paper_trading",
            "name": "Autonomous Paper Trading",
            "role": "Risk-limited paper execution only",
            "category": "trading",
            "enabled": True,
            "overlaps": [],
        },
        {
            "id": "pc_agent",
            "name": "PC Agent",
            "role": "Local supervision, recovery, backup and updates",
            "category": "operations",
            "enabled": True,
            "overlaps": [],
        },
    ]


class ControlPlane:
    def __init__(self, project_root: Path | str | None = None) -> None:
        self.project_root = Path(project_root or os.getenv("SHARIPOVAI_PROJECT_ROOT", ".")).resolve()
        self.runtime = self.project_root / "runtime"
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.command_dir = self.runtime / "commands"
        self.command_dir.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> dict[str, Any]:
        agent = self._load_json(self.runtime / "pc_agent_status.json", {})
        backup = self._backup_status()
        disk = shutil.disk_usage(self.project_root)
        return {
            "status": "ok",
            "generated_at": datetime.now(UTC).isoformat(),
            "node": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "project_root": str(self.project_root),
            },
            "resources": {
                "disk_total": disk.total,
                "disk_used": disk.used,
                "disk_free": disk.free,
                "load_average": self._load_average(),
            },
            "agent": agent,
            "backup": backup,
            "components": component_registry(),
            "manager": self._manager_summary(),
            "control": {
                "safe_commands": sorted(SAFE_COMMANDS),
                "pending": len(list(self.command_dir.glob("*.json"))),
                "arbitrary_shell_enabled": False,
                "real_trading_enabled": False,
            },
        }

    def enqueue(self, action: str, requested_by: str = "dashboard") -> dict[str, Any]:
        if action not in SAFE_COMMANDS:
            raise ValueError(f"Command is not allowed: {action}")
        command_id = f"CMD-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        payload = {
            "id": command_id,
            "action": action,
            "requested_by": requested_by,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "pending",
        }
        target = self.command_dir / f"{command_id}.json"
        self._write_json_atomic(target, payload)
        return payload

    def _backup_status(self) -> dict[str, Any]:
        candidates = list((self.project_root / "backups").rglob("*")) if (self.project_root / "backups").exists() else []
        files = [p for p in candidates if p.is_file()]
        if not files:
            return {"status": "missing", "files": 0, "age_seconds": None}
        newest = max(files, key=lambda p: p.stat().st_mtime)
        return {
            "status": "fresh" if time.time() - newest.stat().st_mtime <= 120 else "stale",
            "files": len(files),
            "age_seconds": round(time.time() - newest.stat().st_mtime, 1),
            "newest": str(newest),
        }

    def _manager_summary(self) -> dict[str, Any]:
        components = component_registry()
        overlaps = sorted({tuple(sorted((item["id"], other))) for item in components for other in item.get("overlaps", [])})
        return {
            "registered": len(components),
            "enabled": sum(1 for item in components if item.get("enabled")),
            "overlap_candidates": [list(pair) for pair in overlaps],
            "policy": "extend existing modules before adding duplicates",
        }

    @staticmethod
    def _load_average() -> list[float] | None:
        try:
            return [round(value, 2) for value in os.getloadavg()]
        except (AttributeError, OSError):
            return None

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    @staticmethod
    def _write_json_atomic(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)
