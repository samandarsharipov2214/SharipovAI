"""Canonical evidence journal for testnet and guarded live executions.

PostgreSQL/SQLite is the source of truth. The JSON file remains a recoverable
operator backup and never controls whether an execution record exists.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from storage import ProjectDatabase, VersionConflict, list_json_items


class ExecutionJournal:
    def __init__(self, path: str | None = None, *, database: ProjectDatabase | None = None) -> None:
        self.path = Path(path or os.getenv("EXECUTION_JOURNAL_FILE", "data/execution_journal.json"))
        self.database = database or ProjectDatabase()
        self.database.initialize()
        self.namespace = "execution_journal"
        self._lock = threading.RLock()
        self._migrate_legacy_once()

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(entry, dict):
            raise TypeError("execution journal entry must be an object")
        now_ms = int(time.time() * 1000)
        event_id = _event_id(entry.get("journal_event_id") or str(uuid.uuid4()))
        item = {
            **entry,
            "journal_event_id": event_id,
            "recorded_at": datetime.fromtimestamp(now_ms / 1000, UTC).isoformat(),
            "recorded_at_ms": now_ms,
        }
        # ProjectDatabase serializes with allow_nan=False and expected_version=0,
        # so one immutable event ID can never be silently overwritten.
        self.database.put_json(self.namespace, event_id, item, expected_version=0)
        try:
            self._write_backup()
        except Exception as exc:
            # DB commit already succeeded. Returning a backup warning prevents a
            # caller from retrying the same financial event as if it were absent.
            return {**item, "backup_status": "error", "backup_error": f"{type(exc).__name__}: {exc}"}
        return {**item, "backup_status": "ok"}

    def load(self) -> dict[str, Any]:
        items = [record["value"] for record in list_json_items(self.database, self.namespace)]
        items.sort(key=lambda row: (int(row.get("recorded_at_ms", 0)), str(row.get("journal_event_id", ""))))
        return {"orders": items}

    def summary(self) -> dict[str, Any]:
        orders = list(self.load().get("orders", []))
        accepted = [item for item in orders if item.get("status") == "accepted"]
        testnet = [item for item in accepted if _environment(item.get("environment") or item.get("mode")) == "testnet"]
        live = [item for item in accepted if _environment(item.get("environment") or item.get("mode")) == "mainnet"]
        unresolved = [item for item in orders if item.get("status") in {"reserved", "submitted", "unresolved"}]
        return {
            "recorded_orders": len(orders),
            "accepted_orders": len(accepted),
            "verified_testnet_orders": len(testnet),
            "verified_live_orders": len(live),
            "unresolved_orders": len(unresolved),
            "last_order": orders[-1] if orders else None,
            "database_backed": True,
            "retention_truncated": False,
        }

    def _migrate_legacy_once(self) -> None:
        if self.database.get_json("migrations", "execution_journal_json_v1") is not None:
            return
        imported = 0
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                rows = raw.get("orders", []) if isinstance(raw, dict) else []
            except Exception:
                rows = []
            for index, entry in enumerate(rows):
                if not isinstance(entry, dict):
                    continue
                canonical = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                event_id = "legacy_" + hashlib.sha256(f"{index}:{canonical}".encode()).hexdigest()[:40]
                recorded_at = str(entry.get("recorded_at") or "")
                item = {
                    **entry,
                    "journal_event_id": event_id,
                    "recorded_at": recorded_at,
                    "recorded_at_ms": _legacy_timestamp(recorded_at, fallback=index + 1),
                }
                try:
                    self.database.put_json(self.namespace, event_id, item, expected_version=0)
                    imported += 1
                except VersionConflict:
                    if self.database.get_json(self.namespace, event_id) is None:
                        raise
        marker = {"completed": True, "imported": imported, "completed_at_ms": int(time.time() * 1000)}
        try:
            self.database.put_json("migrations", "execution_journal_json_v1", marker, expected_version=0)
        except VersionConflict:
            if self.database.get_json("migrations", "execution_journal_json_v1") is None:
                raise
        try:
            self._write_backup()
        except Exception:
            # Migration is complete in the source of truth. A later append or
            # operator repair will refresh the non-authoritative JSON backup.
            pass

    def _write_backup(self) -> None:
        with self._lock:
            data = self.load()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
            try:
                with temp.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, self.path)
            finally:
                temp.unlink(missing_ok=True)


def _event_id(value: Any) -> str:
    text = str(value).strip()
    if not text or len(text) > 200 or not all(char.isalnum() or char in "._:-" for char in text):
        raise ValueError("invalid journal_event_id")
    return text


def _legacy_timestamp(value: Any, *, fallback: int) -> int:
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except Exception:
        return fallback


def _environment(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if clean in {"sandbox", "testnet"}:
        return "testnet"
    if clean in {"live", "mainnet"}:
        return "mainnet"
    return ""
