"""Persistent evidence journal for testnet and guarded live executions."""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class ExecutionJournal:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("EXECUTION_JOURNAL_FILE", "data/execution_journal.json"))
        self._lock = _shared_path_lock(self.path)
        configured = _integer(os.getenv("EXECUTION_JOURNAL_DIAGNOSTIC_LIMIT", "2000"), 2000)
        self.diagnostic_limit = min(max(configured, 100), 10_000)

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise TypeError("execution journal entry must be an object")
        with self._transaction():
            data = self._load_unlocked()
            item = {"recorded_at": datetime.now(UTC).isoformat(), **entry}
            rows = list(data.get("orders", []))
            rows.append(item)
            data["orders"] = _retain_evidence(rows, self.diagnostic_limit)
            self._write_unlocked(data)
            return item

    def load(self) -> dict[str, Any]:
        with self._transaction():
            return self._load_unlocked()

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"execution journal is unreadable: {type(exc).__name__}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("orders", []), list):
            raise RuntimeError("execution journal has invalid structure")
        return data

    def summary(self) -> dict[str, Any]:
        orders = list(self.load().get("orders", []))
        accepted = [item for item in orders if isinstance(item, dict) and item.get("status") == "accepted"]
        testnet = [item for item in accepted if item.get("mode") == "sandbox"]
        live = [item for item in accepted if item.get("mode") == "live"]
        return {
            "recorded_orders": len(orders),
            "accepted_orders": len(accepted),
            "verified_testnet_orders": len(testnet),
            "verified_live_orders": len(live),
            "last_order": orders[-1] if orders else None,
        }

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            deadline = time.monotonic() + 10.0
            descriptor = None
            while descriptor is None:
                try:
                    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("timed out waiting for execution journal lock")
                    time.sleep(0.01)
            try:
                yield
            finally:
                os.close(descriptor)
                lock_path.unlink(missing_ok=True)

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


def _retain_evidence(rows: list[Any], diagnostic_limit: int) -> list[Any]:
    diagnostic_indices = [
        index for index, row in enumerate(rows)
        if not isinstance(row, dict) or row.get("status") != "accepted"
    ]
    keep_diagnostics = set(diagnostic_indices[-diagnostic_limit:])
    return [
        row for index, row in enumerate(rows)
        if (isinstance(row, dict) and row.get("status") == "accepted") or index in keep_diagnostics
    ]


def _shared_path_lock(path: Path) -> threading.RLock:
    key = str(path.expanduser().resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _integer(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
