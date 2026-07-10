"""Persistent evidence journal for testnet and guarded live executions."""
from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ExecutionJournal:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("EXECUTION_JOURNAL_FILE", "data/execution_journal.json"))
        self._lock = threading.RLock()

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            data = self.load()
            item = {"recorded_at": datetime.now(UTC).isoformat(), **entry}
            data.setdefault("orders", []).append(item)
            data["orders"] = data["orders"][-2000:]
            self._write(data)
            return item

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"orders": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"orders": []}
        except Exception:
            return {"orders": []}

    def summary(self) -> dict[str, Any]:
        orders = list(self.load().get("orders", []))
        accepted = [item for item in orders if item.get("status") == "accepted"]
        testnet = [item for item in accepted if item.get("mode") == "sandbox"]
        live = [item for item in accepted if item.get("mode") == "live"]
        return {
            "recorded_orders": len(orders),
            "accepted_orders": len(accepted),
            "verified_testnet_orders": len(testnet),
            "verified_live_orders": len(live),
            "last_order": orders[-1] if orders else None,
        }

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)
