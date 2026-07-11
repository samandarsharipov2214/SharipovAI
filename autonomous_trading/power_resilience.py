"""Power-loss resilience for SharipovAI local state.

Critical state files are flushed every ten seconds, copied to a last-known-good
backup, and restored automatically when the primary JSON file is damaged after
an abrupt power loss. Critical execution events should still persist immediately.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from persistence_paths import durable_data_path


DEFAULT_STATE_FILES = (
    "market_stream.json",
    "multi_exchange_market.json",
    "autonomous_paper.json",
    "testnet_bridge.json",
    "execution_journal.json",
    "news_market_impact.json",
    "news_agent_network.json",
    "unified_memory.json",
)


class PowerResilienceManager:
    """Create durable checkpoints and recover the last valid JSON state."""

    def __init__(self, files: Iterable[str | Path] | None = None) -> None:
        self.interval_seconds = max(float(os.getenv("POWER_CHECKPOINT_SECONDS", "10")), 1.0)
        self.root = _data_root()
        configured = files or [self.root / name for name in DEFAULT_STATE_FILES]
        self.files = [Path(item) for item in configured]
        self.manifest_path = self.root / "power_checkpoint_manifest.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_result: dict[str, Any] = {"status": "not_started"}

    def start(self) -> dict[str, Any]:
        recovery = self.recover_all()
        self.checkpoint()
        if not self._thread or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="power-resilience", daemon=True)
            self._thread.start()
        return {"status": "started", "recovery": recovery, "interval_seconds": self.interval_seconds}

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        final = self.checkpoint()
        return {"status": "stopped", "final_checkpoint": final}

    def checkpoint(self) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        results: list[dict[str, Any]] = []
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            for path in self.files:
                result = self._checkpoint_file(path)
                results.append(result)
            payload = {
                "status": "ok" if all(item["status"] in {"saved", "missing"} for item in results) else "warning",
                "checkpointed_at": now,
                "interval_seconds": self.interval_seconds,
                "files": results,
            }
            _atomic_json_write(self.manifest_path, payload)
            self._last_result = payload
            return payload

    def recover_all(self) -> dict[str, Any]:
        recovered: list[str] = []
        healthy: list[str] = []
        missing: list[str] = []
        failed: list[dict[str, str]] = []
        with self._lock:
            for path in self.files:
                if _valid_json(path):
                    healthy.append(str(path))
                    continue
                backup = _backup_path(path)
                if _valid_json(backup):
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup, path)
                        _fsync_file(path)
                        recovered.append(str(path))
                    except OSError as exc:
                        failed.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
                elif not path.exists() and not backup.exists():
                    missing.append(str(path))
                else:
                    failed.append({"path": str(path), "error": "primary and backup are invalid"})
        return {"status": "ok" if not failed else "warning", "recovered": recovered, "healthy": healthy, "missing": missing, "failed": failed}

    def status(self) -> dict[str, Any]:
        return {
            **self._last_result,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "root": str(self.root),
            "interval_seconds": self.interval_seconds,
        }

    def _checkpoint_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"path": str(path), "status": "missing"}
        if not _valid_json(path):
            return {"path": str(path), "status": "invalid", "error": "primary JSON is invalid"}
        try:
            _fsync_file(path)
            backup = _backup_path(path)
            backup.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(str(backup) + ".tmp")
            shutil.copy2(path, temp)
            _fsync_file(temp)
            os.replace(temp, backup)
            _fsync_directory(backup.parent)
            return {"path": str(path), "backup": str(backup), "status": "saved", "size_bytes": path.stat().st_size}
        except OSError as exc:
            return {"path": str(path), "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.checkpoint()


def _data_root() -> Path:
    explicit = os.getenv("SHARIPOVAI_DATA_DIR") or os.getenv("RENDER_DISK_PATH")
    if explicit:
        return Path(explicit)
    if os.name == "nt":
        return Path(r"D:\SharipovAI\data")
    return durable_data_path("POWER_CHECKPOINT_MANIFEST", "data/power_checkpoint_manifest.json").parent


def _backup_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lastgood")


def _valid_json(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(str(path) + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    _fsync_directory(path.parent)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
