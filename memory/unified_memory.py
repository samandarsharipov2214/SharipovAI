"""Shared namespaced memory for all SharipovAI surfaces and agents."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryItem:
    namespace: str
    key: str
    value: dict[str, Any]
    source: str
    updated_at: int
    version: int = 1


class UnifiedMemory:
    """Atomic JSON memory shared by Telegram, dashboard and internal agents."""

    DEFAULT_PATH = Path(os.getenv("SHARIPOVAI_UNIFIED_MEMORY_FILE", "data/unified_memory.json"))

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or self.DEFAULT_PATH)
        self._lock = threading.RLock()

    def put(self, namespace: str, key: str, value: dict[str, Any], *, source: str) -> MemoryItem:
        namespace = self._clean(namespace)
        key = self._clean(key)
        if not isinstance(value, dict):
            raise TypeError("UnifiedMemory value must be a dictionary.")
        with self._lock:
            items = self._load()
            identity = f"{namespace}:{key}"
            previous = items.get(identity, {})
            item = MemoryItem(
                namespace=namespace,
                key=key,
                value=value,
                source=self._clean(source),
                updated_at=int(time.time()),
                version=int(previous.get("version", 0)) + 1,
            )
            items[identity] = asdict(item)
            self._write(items)
            return item

    def get(self, namespace: str, key: str) -> MemoryItem | None:
        raw = self._load().get(f"{self._clean(namespace)}:{self._clean(key)}")
        return MemoryItem(**raw) if isinstance(raw, dict) else None

    def list_namespace(self, namespace: str) -> list[MemoryItem]:
        normalized = self._clean(namespace)
        return sorted(
            (MemoryItem(**raw) for raw in self._load().values() if raw.get("namespace") == normalized),
            key=lambda item: (item.updated_at, item.key),
            reverse=True,
        )

    def health(self) -> dict[str, Any]:
        try:
            items = self._load()
            return {"ok": True, "item_count": len(items), "path": str(self.path)}
        except Exception as exc:
            return {"ok": False, "item_count": 0, "path": str(self.path), "error": f"{type(exc).__name__}: {exc}"}

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}

    def _write(self, payload: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _clean(value: str) -> str:
        normalized = str(value).strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("Memory namespace, key and source must not be empty.")
        return normalized
